import threading

from .events import EventBus
from .health import HealthManager, HealthStatus
from .processes import ProcessManager
from .local_services import LocalServicesManager
from .state import StateManager
from .watchdog import FilesystemWatchRegistry, Watchdog
from .orchestrator import AutonomousOrchestrator
from .config import ConfigManager
from .logging import configure_logging
from .mode import RUNTIME_MODE
from .emergency import EmergencyStopCoordinator
from .recovery import RecoveryEngine
from .state_machine import JarvisState, JarvisStateMachine
from app_paths import data_path, data_directory
from .diagnostics import DiagnosticsRunner
from jarvis_missions import MissionEngine, MissionStore
from jarvis_memory import MemoryStore
from jarvis_search import UniversalSearch
from pathlib import Path
from jarvis_skills import Capability, SkillManifest, SkillRegistry
from jarvis_skills.builtin import register_builtin_skills
from jarvis_skills.desktop import register_browser_skills, register_desktop_skills
from jarvis_skills.applications import register_application_skills
from jarvis_integrations.service import get_integration_service
from jarvis_integrations.ufo_sidecar import UFOSidecarManager
from jarvis_integrations.skills import register_integration_skills
from jarvis_expansion import ExpansionClient, ExpansionSidecarManager, register_expansion_skills
from permission_manager import decision as permission_decision
from jarvis_perception import PerceptionEngine, VerifiedActionRunner
from jarvis_perception.adapters import configure_default_observers
from jarvis_voice import VoiceSessionEngine, VoiceState
from jarvis_voice.health import probe_audio_input, probe_audio_output, probe_wake_model
from performance_metrics import record_tool
from jarvis_developer import DeveloperService
from jarvis_automation import AutomationEngine
from jarvis_companion import CompanionEngine
from jarvis_broker import BrokerManager
from jarvis_windows import WindowManager, WindowsUIAgent
from async_engine import ENGINE as ASYNC_ENGINE
from jarvis_files import FileAgent, FileIndexer, FileOperation
from jarvis_plugins import PluginManager
from jarvis_apps import AppManager
from jarvis_system import (
    ClipboardManager,
    ContextEngine,
    HardwareEventMonitor,
    NetworkAgent,
    NotificationCenter,
    SystemInformation,
    StartupManager,
    RuntimePerformanceMonitor,
)
from jarvis_vault import CredentialVault
from dataclasses import asdict
from audit_log import recent as recent_audit, record_action
from .world_model import WorldModel
from .cognitive_core import UnifiedCognitiveCore
import sys
import time


class CoreRuntime:
    """Owns Phase-1 services and their deterministic lifecycle."""

    def __init__(self):
        project_root = Path(__file__).resolve().parent.parent
        self.config = ConfigManager({"watchdog_enabled": True, "watchdog_interval": 2.0}, project_root / "config")
        self.logger = configure_logging(data_path("logs") / "jarvis.jsonl")
        self.events = EventBus(self.logger)
        self.state = StateManager(self.events)
        self.notifications = NotificationCenter(self.events)
        self.filesystem_watchers = FilesystemWatchRegistry(self.events, self.notifications, self.logger)
        self.emergency = EmergencyStopCoordinator(self.events)
        self.recovery = RecoveryEngine(self.events)
        self.state_machine = JarvisStateMachine(self.events)
        self.health = HealthManager(self.events)
        self.processes = ProcessManager(self.events)
        self.local_services = LocalServicesManager(self.processes, self.logger)
        self._stop_lock = threading.RLock()
        self._stopped = False
        self.voice = VoiceSessionEngine(self._speak, self._stop_speaker, self._voice_state, record_metric=record_tool)
        permission_map = {
            Capability.READ_SCREEN: "computer",
            Capability.CONTROL_MOUSE: "computer",
            Capability.CONTROL_KEYBOARD: "computer",
            Capability.READ_FILES: "files_read",
            Capability.WRITE_FILES: "files_write",
            Capability.PROCESS_CONTROL: "scripts",
            Capability.NETWORK: "external_send",
            Capability.BROWSER_CONTROL: "computer",
            Capability.SYSTEM_SETTINGS: "admin",
        }
        self.mode = RUNTIME_MODE
        self.broker = BrokerManager()
        self.vault = CredentialVault(data_path("vault") / "credentials.db")
        self.startup = StartupManager(self.broker, project_root)
        self.windows = WindowManager() if sys.platform == "win32" else None
        self.app_manager = AppManager(self.broker, self.processes, self.windows)
        self.windows_ui = WindowsUIAgent()
        user_root = Path.home()
        index_roots = [
            path for path in (user_root / "Desktop", user_root / "Documents", user_root / "Downloads") if path.exists()
        ]
        self.network = NetworkAgent()
        self.clipboard = ClipboardManager(index_roots)
        self.hardware_events = HardwareEventMonitor(self.events)
        self.file_index = FileIndexer(
            data_path("search") / "files.db", index_roots or [Path(__file__).resolve().parent.parent]
        )
        self.file_agent = FileAgent(
            index_roots or [project_root],
            data_path("file_transactions"),
            massive_threshold=int(self.config.get("permissions", {}).get("mass_file_threshold", 20)),
        )
        self.skills = SkillRegistry(
            data_path("metrics") / "skills.db",
            lambda capability: self._authorize_capability(capability, permission_map),
            self._authorize_skill,
            record_action,
        )
        register_builtin_skills(self.skills, Path(__file__).resolve().parent.parent, self.processes)
        self.skills.register(
            SkillManifest(
                "watchdog.start",
                "1.0.0",
                "Start an owned in-process filesystem watcher",
                ("monitora cartella", "controlla cartella", "tieni d'occhio cartella", "avvisami quando cambia una cartella"),
                frozenset({Capability.READ_FILES}),
                "runtime:watchdog_start",
            ),
            lambda path, events=None, recursive=False, debounce_ms=750, filters=None: self.filesystem_watchers.start(
                path, events=events, recursive=bool(recursive), debounce_ms=int(debounce_ms), filters=filters
            ),
        )
        self.skills.register(
            SkillManifest(
                "watchdog.stop",
                "1.0.0",
                "Stop an owned filesystem watcher",
                ("smetti di monitorare", "ferma monitoraggio", "ferma tutti i monitoraggi"),
                frozenset({Capability.READ_FILES}),
                "runtime:watchdog_stop",
            ),
            lambda watch_id=None, path=None, all_watchers=False: self.filesystem_watchers.stop_all()
            if bool(all_watchers)
            else self.filesystem_watchers.stop(watch_id=watch_id, path=path),
        )
        self.skills.register(
            SkillManifest(
                "watchdog.list",
                "1.0.0",
                "List owned active filesystem watchers",
                ("quali cartelle stai monitorando", "elenca monitoraggi", "monitoraggi attivi"),
                frozenset({Capability.READ_FILES}),
                "runtime:watchdog_list",
            ),
            lambda: {"success": True, "message": "Monitoraggi attivi elencati.", "data": {"watchers": self.filesystem_watchers.list()}},
        )
        register_desktop_skills(self.skills)
        register_browser_skills(self.skills)
        integration_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else project_root
        self.ufo_sidecar = UFOSidecarManager(integration_root)
        self.integrations = get_integration_service(integration_root)
        register_integration_skills(self.skills, self.integrations)
        self.expansion_sidecar = ExpansionSidecarManager(integration_root)
        self.expansion = ExpansionClient(integration_root)
        register_expansion_skills(self.skills, self.expansion, self.local_services.wait_ready)
        self.memory = MemoryStore(data_path("jarvis_memory.db"))
        self.world = WorldModel(self.memory.working, events=self.events)
        self.mission_store = MissionStore(data_path("missions") / "missions.db")
        self.missions = MissionEngine(
            self.mission_store, memory=self.memory, recovery=self.recovery, authorize=self._authorize_mission
        )
        self.context = ContextEngine(
            self.events, self.state, self.processes, self.memory, self.mission_store, self.windows, world=self.world
        )
        self.automation = AutomationEngine(data_path("automation") / "automation.db", self._dispatch_automation)
        self.automation.bind(self.events)
        self.companion = CompanionEngine(
            self.events,
            self.state,
            self.voice,
            config=self.config.get("companion", {}),
            logger=self.logger,
            persistence_path=data_path("companion") / "preferences.json",
        )
        self.performance_monitor = RuntimePerformanceMonitor(self.voice, self.missions, self.automation)
        self.system_information = SystemInformation(self.windows, self.performance_monitor.gpu)
        register_application_skills(self.skills, self.processes, self.memory, Path(__file__).resolve().parent.parent)
        windows = self.windows
        if windows is not None:
            self.skills.register(
                SkillManifest(
                    "windows.list",
                    "1.0.0",
                    "List top-level Windows windows",
                    ("list windows", "elenca finestre"),
                    frozenset({Capability.READ_SCREEN}),
                    "runtime:windows_list",
                ),
                lambda: {"success": True, "data": {"windows": windows.list()}},
            )
            self.skills.register(
                SkillManifest(
                    "windows.snap",
                    "1.0.0",
                    "Snap a window on a selected monitor",
                    ("snap window", "affianca finestra", "sposta sul monitor"),
                    frozenset({Capability.CONTROL_MOUSE}),
                    "runtime:windows_snap",
                ),
                lambda title, position, monitor=0: {
                    "success": windows.snap(title, position, int(monitor)),
                    "message": "Finestra posizionata",
                },
            )
            self.skills.register(
                SkillManifest(
                    "windows.focus",
                    "1.0.0",
                    "Focus a top-level window",
                    ("focus window", "attiva finestra"),
                    frozenset({Capability.CONTROL_MOUSE}),
                    "runtime:windows_focus",
                ),
                lambda title: {"success": windows.focus(title), "message": "Finestra attivata"},
            )
        self.skills.register(
            SkillManifest(
                "windows.uia.inspect",
                "1.0.0",
                "Inspect the structured accessibility tree",
                ("inspect ui", "leggi controlli"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:uia_inspect",
            ),
            lambda: {"success": True, "data": self.windows_ui._snapshot()},
        )
        self.skills.register(
            SkillManifest(
                "windows.uia.invoke",
                "1.0.0",
                "Invoke a structured UI element",
                ("invoke ui", "clicca controllo"),
                frozenset({Capability.CONTROL_MOUSE}),
                "runtime:uia_invoke",
            ),
            lambda target: self.windows_ui.invoke(target),
        )
        self.skills.register(
            SkillManifest(
                "files.index.scan",
                "1.0.0",
                "Incrementally index safe file metadata and text",
                ("index files", "indicizza file"),
                frozenset({Capability.READ_FILES}),
                "runtime:file_index_scan",
            ),
            lambda limit=100000: {"success": True, "data": asdict(self.file_index.scan(limit=int(limit)))},
        )
        self.skills.register(
            SkillManifest(
                "files.index.search",
                "1.0.0",
                "Search indexed files by name, metadata, time and safe content",
                ("find file", "trova file"),
                frozenset({Capability.READ_FILES}),
                "runtime:file_index_search",
            ),
            lambda query, extension=None, limit=20: {
                "success": True,
                "data": {"results": self.file_index.search(query, extension=extension, limit=int(limit))},
            },
        )
        self.skills.register(
            SkillManifest(
                "files.plan",
                "1.0.0",
                "Validate and summarize transactional file operations",
                ("plan file operations", "pianifica operazioni file"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_plan",
            ),
            lambda operations: {
                "success": True,
                "data": asdict(self.file_agent.plan([FileOperation(**row) for row in operations])),
            },
        )
        self.skills.register(
            SkillManifest(
                "files.plan.dry_run",
                "1.0.0",
                "Simulate a previously validated file plan",
                ("dry run files", "simula operazioni file"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_dry_run",
            ),
            lambda plan_id: (
                {"success": result.success, "data": asdict(result)}
                if (result := self.file_agent.execute_plan(plan_id, dry_run=True))
                else {}
            ),
        )
        self.skills.register(
            SkillManifest(
                "files.plan.execute",
                "1.0.0",
                "Execute a transactional file plan with rollback",
                ("execute file plan", "esegui piano file"),
                frozenset({Capability.WRITE_FILES}),
                "runtime:files_execute",
                risk="sensitive",
            ),
            lambda plan_id: (
                {
                    "success": result.success,
                    "message": "Piano file completato." if result.success else "; ".join(result.errors),
                    "data": asdict(result),
                }
                if (result := self.file_agent.execute_plan(plan_id, confirmed=True))
                else {}
            ),
        )
        self.skills.register(
            SkillManifest(
                "files.rollback",
                "1.0.0",
                "Rollback a completed transactional file plan",
                ("rollback files", "annulla operazioni file"),
                frozenset({Capability.WRITE_FILES}),
                "runtime:files_rollback",
                risk="sensitive",
            ),
            lambda plan_id: (
                {
                    "success": result.success,
                    "message": "Rollback file completato." if result.success else "; ".join(result.errors),
                    "data": asdict(result),
                }
                if (result := self.file_agent.rollback(plan_id))
                else {}
            ),
        )
        self.skills.register(
            SkillManifest(
                "files.metadata",
                "1.0.0",
                "Read file metadata and properties",
                ("file metadata", "proprietà file"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_metadata",
            ),
            lambda path: {"success": True, "data": self.file_agent.metadata(path)},
        )
        self.skills.register(
            SkillManifest(
                "files.checksum",
                "1.0.0",
                "Calculate SHA-256 for a file",
                ("file checksum", "checksum file"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_checksum",
            ),
            lambda path: {"success": True, "data": {"sha256": self.file_agent.checksum(path)}},
        )
        self.skills.register(
            SkillManifest(
                "files.compare",
                "1.0.0",
                "Compare two files by size and SHA-256",
                ("compare files", "confronta file"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_compare",
            ),
            lambda left, right: {"success": True, "data": self.file_agent.compare(left, right)},
        )
        self.skills.register(
            SkillManifest(
                "files.archive.inspect",
                "1.0.0",
                "Inspect ZIP entries without extraction",
                ("inspect archive", "ispeziona archivio"),
                frozenset({Capability.READ_FILES}),
                "runtime:files_archive_inspect",
            ),
            lambda source: {"success": True, "data": self.file_agent.inspect_archive(source)},
        )
        self.skills.register(
            SkillManifest(
                "files.archive.create",
                "1.0.0",
                "Create a new ZIP from allowed paths",
                ("create archive", "comprimi file"),
                frozenset({Capability.READ_FILES, Capability.WRITE_FILES}),
                "runtime:files_archive",
                risk="sensitive",
            ),
            self.file_agent.archive,
        )
        self.skills.register(
            SkillManifest(
                "files.archive.extract",
                "1.0.0",
                "Safely extract ZIP into a new allowed folder",
                ("extract archive", "estrai archivio"),
                frozenset({Capability.READ_FILES, Capability.WRITE_FILES}),
                "runtime:files_extract",
                risk="sensitive",
            ),
            self.file_agent.extract,
        )
        self.skills.register(
            SkillManifest(
                "processes.list",
                "1.0.0",
                "List processes with resource and hierarchy data",
                ("list processes", "elenca processi"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:process_list",
            ),
            lambda limit=500: {"success": True, "data": {"processes": self.processes.inventory(limit)}},
        )
        self.skills.register(
            SkillManifest(
                "processes.restart",
                "1.0.0",
                "Restart a process launched by JARVIS",
                ("restart process", "riavvia processo"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:process_restart",
                risk="sensitive",
            ),
            lambda process_id: {
                "success": self.processes.restart(process_id) is not None,
                "message": "Riavvio processo completato.",
            },
        )
        self.skills.register(
            SkillManifest(
                "processes.kill_tree",
                "1.0.0",
                "Force terminate a JARVIS-owned process tree",
                ("kill process tree", "termina albero processo"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:process_kill_tree",
                risk="destructive",
            ),
            lambda process_id: {
                "success": self.processes.kill_tree(process_id) > 0,
                "message": "Albero processi terminato.",
            },
        )
        self.skills.register(
            SkillManifest(
                "apps.list",
                "1.0.0",
                "Discover installed applications",
                ("list apps", "elenca applicazioni"),
                frozenset({Capability.READ_FILES}),
                "runtime:apps_list",
            ),
            lambda: {"success": True, "data": {"apps": [asdict(item) for item in self.app_manager.discover()]}},
        )
        self.skills.register(
            SkillManifest(
                "apps.open",
                "1.0.0",
                "Open an unambiguous installed application",
                ("open app", "apri applicazione"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:apps_open",
            ),
            self.app_manager.open,
        )
        self.skills.register(
            SkillManifest(
                "apps.close",
                "1.0.0",
                "Gracefully terminate instances of an identified application",
                ("close app", "chiudi applicazione"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:apps_close",
                risk="sensitive",
            ),
            self.app_manager.close,
        )
        self.skills.register(
            SkillManifest(
                "apps.terminate",
                "1.0.0",
                "Terminate processes belonging to an identified application",
                ("terminate app", "termina applicazione"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:apps_terminate",
                risk="destructive",
            ),
            self.app_manager.terminate,
        )
        self.skills.register(
            SkillManifest(
                "apps.close_except",
                "1.0.0",
                "Gracefully close visible applications except an explicit allowlist",
                ("close everything except", "chiudi tutto tranne"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:apps_close_except",
                risk="sensitive",
                verification_strategy="windows_absent_except_allowlist",
            ),
            self.app_manager.close_except,
        )
        self.skills.register(
            SkillManifest(
                "apps.restart",
                "1.0.0",
                "Gracefully close then reopen an identified application",
                ("restart app", "riavvia applicazione"),
                frozenset({Capability.PROCESS_CONTROL}),
                "runtime:apps_restart",
                risk="sensitive",
            ),
            self.app_manager.restart,
        )
        self.skills.register(
            SkillManifest(
                "apps.packages.search",
                "1.0.0",
                "Search exact Winget package candidates",
                ("search package", "cerca pacchetto"),
                frozenset({Capability.NETWORK}),
                "runtime:apps_package_search",
            ),
            self.app_manager.packages,
        )
        for package_action in ("install", "upgrade", "uninstall"):
            localized_intents = {
                "install": ("install app", "installa applicazione", "installa programma"),
                "upgrade": ("upgrade app", "aggiorna applicazione", "aggiorna programma"),
                "uninstall": ("uninstall app", "disinstalla applicazione", "disinstalla programma"),
            }
            self.skills.register(
                SkillManifest(
                    f"apps.{package_action}",
                    "1.0.0",
                    f"{package_action.title()} an exact Winget package",
                    localized_intents[package_action],
                    frozenset({Capability.NETWORK, Capability.SYSTEM_SETTINGS}),
                    f"runtime:apps_{package_action}",
                    risk="admin",
                    timeout=900,
                ),
                lambda package_id, action=package_action: self.app_manager.package_action(action, package_id),
            )
        self.skills.register(
            SkillManifest(
                "context.current",
                "1.0.0",
                "Read current application, task, conversation and system context",
                ("current context", "contesto corrente"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:context_current",
            ),
            lambda: {"success": True, "data": self.context.snapshot()},
        )
        self.skills.register(
            SkillManifest(
                "network.adapters",
                "1.0.0",
                "List network adapters and addresses",
                ("network adapters", "schede di rete"),
                frozenset({Capability.NETWORK}),
                "runtime:network_adapters",
            ),
            lambda: {"success": True, "data": {"adapters": self.network.adapters()}},
        )
        self.skills.register(
            SkillManifest(
                "network.connectivity",
                "1.0.0",
                "Check bounded outbound connectivity",
                ("check internet", "controlla internet"),
                frozenset({Capability.NETWORK}),
                "runtime:network_connectivity",
            ),
            lambda host="1.1.1.1", port=53, timeout=2: self.network.connectivity(host, port, timeout),
        )
        self.skills.register(
            SkillManifest(
                "network.dns",
                "1.0.0",
                "Resolve a validated hostname",
                ("dns lookup", "risolvi dns"),
                frozenset({Capability.NETWORK}),
                "runtime:network_dns",
            ),
            self.network.dns,
        )
        self.skills.register(
            SkillManifest(
                "network.ping",
                "1.0.0",
                "Ping a validated host without shell interpolation",
                ("ping host", "ping"),
                frozenset({Capability.NETWORK}),
                "runtime:network_ping",
            ),
            self.network.ping,
        )
        self.skills.register(
            SkillManifest(
                "clipboard.inspect",
                "1.0.0",
                "Read clipboard once on explicit request",
                ("read clipboard", "leggi appunti"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:clipboard_inspect",
                risk="sensitive",
            ),
            self.clipboard.inspect,
        )
        self.skills.register(
            SkillManifest(
                "clipboard.write_text",
                "1.0.0",
                "Write bounded text to the clipboard",
                ("copy text", "copia testo"),
                frozenset({Capability.CONTROL_KEYBOARD}),
                "runtime:clipboard_write",
            ),
            self.clipboard.write_text,
        )
        self.skills.register(
            SkillManifest(
                "clipboard.summarize",
                "1.0.0",
                "Summarize clipboard text once without persisting its contents",
                ("summarize clipboard", "riassumi appunti", "riassumi gli appunti"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:clipboard_summarize",
                risk="sensitive",
            ),
            self.clipboard.summarize,
        )
        self.skills.register(
            SkillManifest(
                "clipboard.save_image",
                "1.0.0",
                "Save a clipboard image inside an allowed user folder",
                ("save clipboard image", "salva immagine copiata"),
                frozenset({Capability.READ_SCREEN, Capability.WRITE_FILES}),
                "runtime:clipboard_save",
                risk="sensitive",
            ),
            self.clipboard.save_image,
        )
        self.skills.register(
            SkillManifest(
                "notifications.show",
                "1.0.0",
                "Publish a bounded HUD notification",
                ("show notification", "mostra notifica"),
                frozenset(),
                "runtime:notification",
            ),
            lambda title, message, level="info": {
                "success": True,
                "data": self.notifications.notify(title, message, level),
            },
        )
        self.skills.register(
            SkillManifest(
                "system.information",
                "1.0.0",
                "Read hardware, OS, storage, battery, monitor and audio information",
                ("system information", "informazioni sistema"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:system_information",
            ),
            lambda: {"success": True, "data": self.system_information.snapshot()},
        )
        self.skills.register(
            SkillManifest(
                "system.performance_diagnose",
                "1.0.0",
                "Identify CPU and memory pressure without terminating processes",
                ("what is slowing the computer", "cosa rallenta il computer"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:performance_diagnose",
            ),
            self.performance_monitor.system_pressure,
        )
        self.skills.register(
            SkillManifest(
                "system.memory_optimize",
                "1.0.0",
                "Release unused memory owned by JARVIS without touching other applications",
                ("free memory", "libera memoria"),
                frozenset({Capability.SYSTEM_SETTINGS}),
                "runtime:memory_optimize",
                risk="sensitive",
            ),
            self.performance_monitor.optimize_own_memory,
        )
        self.skills.register(
            SkillManifest(
                "startup.status",
                "1.0.0",
                "Read delayed Windows startup task status",
                ("startup status", "stato avvio automatico"),
                frozenset({Capability.READ_SCREEN}),
                "runtime:startup_status",
            ),
            self.startup.status,
        )
        self.skills.register(
            SkillManifest(
                "startup.enable",
                "1.0.0",
                "Enable delayed per-user Windows startup",
                ("enable startup", "attiva avvio automatico"),
                frozenset({Capability.SYSTEM_SETTINGS}),
                "runtime:startup_enable",
                risk="admin",
            ),
            self.startup.enable,
        )
        self.skills.register(
            SkillManifest(
                "startup.disable",
                "1.0.0",
                "Disable JARVIS Windows startup task",
                ("disable startup", "disattiva avvio automatico"),
                frozenset({Capability.SYSTEM_SETTINGS}),
                "runtime:startup_disable",
                risk="admin",
            ),
            self.startup.disable,
        )
        broker_skills = (
            ("broker.system_info", "system.info", "Read elevated Windows system inventory", "safe"),
            ("broker.software_list", "software.list", "List installed software from Windows registry", "safe"),
            ("broker.service_list", "service.list", "List Windows services", "safe"),
            ("broker.firewall_list", "firewall.list", "Read Windows Firewall profiles", "safe"),
            ("broker.task_list", "task.list", "List scheduled tasks", "safe"),
            ("broker.driver_list", "driver.list", "List third-party Windows drivers", "safe"),
            ("broker.update_history", "windows_update.history", "Read Windows Update history", "safe"),
            ("broker.service_start", "service.start", "Start a validated Windows service", "admin"),
            ("broker.service_stop", "service.stop", "Stop a validated Windows service", "admin"),
            ("broker.firewall_profile", "firewall.profile", "Change a Windows Firewall profile state", "admin"),
            ("broker.firewall_rule_add", "firewall.rule_add", "Add a program-scoped firewall rule", "admin"),
            ("broker.firewall_rule_remove", "firewall.rule_remove", "Remove a named firewall rule", "admin"),
            ("broker.task_enable", "task.enable", "Enable an existing scheduled task", "admin"),
            ("broker.task_disable", "task.disable", "Disable an existing scheduled task", "admin"),
            ("broker.driver_scan", "driver.scan", "Request a Windows Plug and Play device scan", "admin"),
            ("broker.update_scan", "windows_update.scan", "Request a Windows Update scan", "admin"),
            ("broker.software_upgrade_all", "winget.upgrade_all", "Upgrade all applicable Winget packages", "admin"),
            ("broker.power_lock", "power.lock", "Lock the current Windows session", "sensitive"),
            ("broker.power_logout", "power.logout", "Log out of the current Windows session", "destructive"),
            ("broker.power_shutdown", "power.shutdown", "Shut down Windows", "destructive"),
            ("broker.power_restart", "power.restart", "Restart Windows", "destructive"),
        )
        for skill_name, broker_action, description, risk in broker_skills:
            capability = Capability.READ_SCREEN if risk == "safe" else Capability.SYSTEM_SETTINGS
            self.skills.register(
                SkillManifest(
                    skill_name,
                    "1.0.0",
                    description,
                    (skill_name.replace("broker.", "").replace("_", " "),),
                    frozenset({capability}),
                    f"broker:{broker_action}",
                    risk=risk,
                    timeout=1800 if broker_action == "winget.upgrade_all" else 120,
                    verification_strategy="broker_exit_code",
                ),
                lambda _action=broker_action, **parameters: self._broker_action(_action, parameters),
            )
        self.plugins = PluginManager(self.skills, self.events)
        self.plugins.load_all(Path(__file__).resolve().parent.parent / "plugins")
        self.search = UniversalSearch(
            Path(__file__).resolve().parent.parent, self.memory, self.mission_store, data_path(".")
        )
        self.developer = DeveloperService(
            Path(__file__).resolve().parent.parent, data_path("developer"), Path(sys.executable)
        )
        self.doctor = DiagnosticsRunner(Path(__file__).resolve().parent.parent, data_directory())
        # Coordinator over the existing planner, router, registry and mission
        # state.  It does not introduce another executor or memory store.
        self.orchestrator = AutonomousOrchestrator(self.skills, self.state)
        self.skills.register(
            SkillManifest(
                "developer.inspect",
                "1.0.0",
                "Analyze repository architecture and syntax",
                ("inspect repository", "analizza repository"),
                frozenset({Capability.READ_FILES}),
                "runtime:developer_inspect",
            ),
            lambda: self.developer.inspect(),
        )
        self.skills.register(
            SkillManifest(
                "developer.lab_create",
                "1.0.0",
                "Create isolated LAB workspace",
                ("create lab", "crea lab"),
                frozenset({Capability.READ_FILES, Capability.WRITE_FILES}),
                "runtime:lab_create",
            ),
            lambda: self.developer.create_lab(),
        )
        self.skills.register(
            SkillManifest(
                "developer.lab_patch",
                "1.0.0",
                "Apply transactional files in LAB",
                ("patch lab", "modifica lab"),
                frozenset({Capability.WRITE_FILES}),
                "runtime:lab_patch",
            ),
            lambda lab_id, files: self.developer.patch(lab_id, files),
        )
        self.skills.register(
            SkillManifest(
                "developer.lab_test",
                "1.0.0",
                "Run LAB tests in isolated Python",
                ("test lab", "testa lab"),
                frozenset({Capability.PROCESS_CONTROL, Capability.READ_FILES}),
                "runtime:lab_test",
            ),
            lambda lab_id, timeout=120: self.developer.test(lab_id, timeout),
        )
        self.skills.register(
            SkillManifest(
                "developer.lab_promote",
                "1.0.0",
                "Promote verified LAB files with rollback",
                ("promote lab", "promuovi lab"),
                frozenset({Capability.PROCESS_CONTROL, Capability.READ_FILES, Capability.WRITE_FILES}),
                "runtime:lab_promote",
            ),
            lambda lab_id, paths, timeout=120: self.developer.promote(lab_id, paths, timeout),
        )
        self.perception = PerceptionEngine()
        configure_default_observers(self.perception)
        self.world.bind_context(self.context)
        self.world.bind_perception(self.perception)
        self.cognition = UnifiedCognitiveCore(
            registry=self.skills,
            context=self.context,
            world=self.world,
            memory=self.memory.working,
            state=self.state,
            events=self.events,
        )
        self.actions = VerifiedActionRunner(self.perception)
        self.watchdog = Watchdog(self.health)
        self.watchdog.register(
            "core", lambda: self.state.get("running", False), interval=self.config.get("watchdog_interval")
        )
        self.watchdog.register("wake_word", lambda: probe_wake_model(project_root / "model-it"), interval=30)
        self.watchdog.register("audio_input", probe_audio_input, interval=30)
        self.watchdog.register("audio_output", probe_audio_output, interval=30)
        self.watchdog.register("broker", lambda: False if self.mode.safe else self.broker.health(), interval=30)
        self._runtime_started_at = time.monotonic()
        self._hud_last_heartbeat = None
        self.events.subscribe("hud.heartbeat", lambda event: setattr(self, "_hud_last_heartbeat", time.monotonic()))
        self.watchdog.register(
            "hud",
            lambda: self._hud_last_heartbeat is not None
            and time.monotonic() - self._hud_last_heartbeat < 8
            or self._hud_last_heartbeat is None
            and time.monotonic() - self._runtime_started_at < 30,
            interval=3,
        )
        self.watchdog.register("event_bus", self._probe_event_bus, interval=15)
        self.watchdog.register("memory", lambda: self.memory.path.exists(), interval=30)
        self.watchdog.register("screen_perception", lambda: isinstance(self.perception.snapshot(), dict), interval=15)
        self.watchdog.register(
            "companion",
            lambda: self.companion.snapshot().get("running", False),
            interval=10,
            recover=self._restart_companion,
            failure_threshold=2,
        )
        self.watchdog.register(
            "hardware_events",
            self.hardware_events.healthy,
            interval=10,
            recover=self.hardware_events.restart,
            failure_threshold=2,
        )
        self.watchdog.register(
            "automation_events",
            self.automation.healthy,
            interval=10,
            recover=self.automation.restart_events,
            failure_threshold=2,
        )
        self.emergency.register("async", ASYNC_ENGINE.cancel_all)
        self.emergency.register("missions", self.missions.cancel_all)
        self.emergency.register("processes", self.processes.terminate_all)
        self.emergency.register("automation", self.automation.pause)
        self.emergency.register("voice", self._emergency_voice_stop)
        self.emergency.register("input", self._release_input)
        self.emergency.register("state", self.state_machine.emergency_idle)

    def start(self) -> None:
        with self._stop_lock:
            self._stopped = False
        self.state.set("running", True)
        self.state.set("safe_mode", self.mode.safe)
        self.state_machine.transition(JarvisState.IDLE, reason="startup_complete")
        self.health.report("core", HealthStatus.HEALTHY, "Foundation runtime started")
        if self.config.get("watchdog_enabled"):
            self.watchdog.start()
        self.logger.info("core.started")
        self.events.publish("core.started")
        migration = self.memory.migrate_legacy()
        self.logger.info("memory.migrated", extra=migration)
        try:
            if self.ufo_sidecar.auto_start:
                if self.ufo_sidecar.start():
                    self.logger.info("ufo.sidecar.started")
                else:
                    self.logger.warning("ufo.sidecar.unavailable", extra={"error": self.ufo_sidecar.snapshot().get("error", "")})
        except Exception as exc:
            self.logger.warning("ufo.sidecar.start_failed", extra={"error": str(exc)})
        try:
            if self.expansion_sidecar.auto_start:
                if self.expansion_sidecar.start():
                    self.logger.info("expansion.sidecar.started")
                else:
                    self.logger.warning(
                        "expansion.sidecar.unavailable",
                        extra={"error": self.expansion_sidecar.snapshot().get("error", "")},
                    )
        except Exception as exc:
            self.logger.warning("expansion.sidecar.start_failed", extra={"error": str(exc)})
        self.local_services.start_background()
        self.companion.start()
        self.hardware_events.start()

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        self.events.publish("core.stopping")
        cleanup = (
            ("hardware", self.hardware_events.stop),
            ("windows_ui", self.windows_ui.close),
            ("context", self.context.close),
            ("world", self.world.close),
            ("plugins", self.plugins.close),
            ("companion", self.companion.stop),
            ("filesystem_watchers", self.filesystem_watchers.shutdown),
            ("watchdog", self.watchdog.stop),
            ("voice", self.voice.shutdown),
            ("missions", self.missions.shutdown),
            ("automation", self.automation.close),
            ("recovery", self.recovery.shutdown),
            ("ufo_sidecar", self.ufo_sidecar.stop),
            ("expansion_sidecar", self.expansion_sidecar.stop),
            ("local_services", self.local_services.stop),
            ("processes", self.processes.shutdown),
        )
        for name, operation in cleanup:
            try:
                operation()
            except Exception as exc:
                self.logger.warning(f"{name}.stop_failed", extra={"error": str(exc)})
        self.state.set("running", False)
        self.health.report("core", HealthStatus.DISABLED, "Foundation runtime stopped")
        self.logger.info("core.stopped")

    def diagnostics(self) -> dict:
        return {
            "health": self.health.snapshot(),
            "state": self.state.snapshot(),
            "processes": self.processes.snapshot(),
            "missions": self.mission_store.recent(),
            "memory": {"working": self.memory.working.snapshot(), "recent": self.memory.search(limit=5)},
            "skills": {"registered": self.skills.list(), "metrics": self.skills.metrics()},
            "orchestration": self.orchestrator.snapshot(),
            "cognition": self.cognition.snapshot(),
            "integrations": self.integrations.status(deep=False),
            "ufo_sidecar": self.ufo_sidecar.snapshot(),
            "expansion": self.expansion.status(deep=False),
            "expansion_sidecar": self.expansion_sidecar.snapshot(),
            "local_services": self.local_services.snapshot(),
            "actions": recent_audit(100),
            "plugins": self.plugins.snapshot(),
            "context": self.context.snapshot(),
            "filesystem_watchers": self.filesystem_watchers.list(),
            "network": {"adapters": self.network.adapters()},
            "system_information": self.system_information.snapshot(),
            "performance_monitor": self.performance_monitor.snapshot(),
            "notifications": self.notifications.snapshot(),
            "vault": {"entries": len(self.vault.list()), "protected": sys.platform == "win32"},
            "perception": self.perception.snapshot(),
            "voice": {**self.voice.snapshot(), **self._voice_provider_status()},
            "automation": self.automation.report(),
            "companion": self.companion.snapshot(),
            "broker": {"enabled": not self.mode.safe, "healthy": False if self.mode.safe else self.broker.health()},
            "windows": {
                "available": self.windows is not None,
                "active": self._active_window_title(),
            },
            "emergency": {"active": self.emergency.active},
            "assistant_state": self.state_machine.state.value,
            "doctor": self.doctor.run(),
            "config": self.config.snapshot(),
        }

    @staticmethod
    def _speak(text: str, interruptible: bool):
        import voice

        return voice.parla(text, interrompibile=interruptible)

    @staticmethod
    def _stop_speaker(new_text: str | None):
        import voice

        voice.richiedi_stop_voce(new_text)

    @staticmethod
    def _voice_provider_status() -> dict:
        try:
            import voice

            return voice.voice_status()
        except Exception:
            return {"provider": "unavailable", "status": "OFFLINE"}

    def _voice_state(self, status: VoiceState):
        self.state.set("voice", status.value, source="voice")
        health = (
            HealthStatus.FAILED
            if status == VoiceState.ERROR
            else HealthStatus.DISABLED if status == VoiceState.STOPPED else HealthStatus.HEALTHY
        )
        self.health.report("voice", health, status.value)

    def _emergency_voice_stop(self):
        self.voice.interrupt()
        self.voice.cancel_pending()
        self._stop_speaker(None)

    @staticmethod
    def _release_input():
        import pyautogui

        for button in ("left", "middle", "right"):
            pyautogui.mouseUp(button=button)
        for key in ("ctrl", "alt", "shift", "win", "enter", "space"):
            pyautogui.keyUp(key)

    def _dispatch_automation(self, action: dict) -> dict:
        skill = str(action.get("skill") or "").strip()
        if skill:
            result = self.skills.execute(skill, **dict(action.get("arguments") or {}))
            return {"success": result.success, "message": result.message, "data": result.data}
        command = str(action.get("command") or "").strip()
        if not command:
            return {"success": False, "message": "azione vuota"}
        self.events.publish("automation.command", {"command": command}, source="automation")
        return {"success": True, "message": "comando consegnato al dispatcher"}

    def write_text_file(self, path: str, content: str) -> dict:
        """Write text through the existing transactional FileAgent.

        The explicit WRITE_FILES permission is checked before the plan is
        created.  FileAgent then validates the allowed root, journals the
        operation and the result is checked again by reading the exact file
        that was written.
        """
        permission = permission_decision("files_write")
        if permission == "deny":
            return {"successo": False, "messaggio": "Scrittura bloccata dal profilo di autorizzazione corrente."}
        if permission != "allow":
            return {"successo": False, "richiede_conferma": True, "messaggio": "Conferma richiesta per la scrittura del file."}
        target = Path(path).expanduser().resolve()
        try:
            plan = self.file_agent.plan(
                [FileOperation("write", target=str(target), content=str(content))]
            )
            operation = self.file_agent.execute(plan, confirmed=True)
            if not operation.success:
                return {
                    "successo": False,
                    "messaggio": "; ".join(operation.errors) or "Scrittura del file non riuscita.",
                    "dati": {"plan_id": operation.plan_id, "completed": operation.completed},
                }
            if not target.is_file() or target.read_text(encoding="utf-8") != str(content):
                return {
                    "successo": False,
                    "messaggio": "Scrittura eseguita ma il contenuto non è stato verificato.",
                    "dati": {"path": str(target), "plan_id": operation.plan_id},
                }
            return {
                "successo": True,
                "messaggio": "File scritto e verificato.",
                "dati": {
                    "path": str(target),
                    "size": target.stat().st_size,
                    "plan_id": operation.plan_id,
                    "verified": True,
                },
                "verification": {
                    "status": "verified",
                    "strength": 1.0,
                    "evidence": f"Contenuto verificato in {target}",
                },
            }
        except Exception as exc:
            from .logging import redact

            return {"successo": False, "messaggio": "Non sono riuscito a scrivere il file.", "errore": redact(repr(exc))}

    def _broker_action(self, action: str, parameters: dict) -> dict:
        from jarvis_broker.protocol import BrokerProtocol
        from permission_engine import RiskLevel

        risk = BrokerProtocol.ACTION_RISKS[action]
        if not self.broker.ensure_available():
            return {"success": False, "message": "Broker amministrativo non disponibile."}
        response = self.broker.client.execute(
            action,
            dict(parameters),
            confirmed=risk in {RiskLevel.SENSITIVE, RiskLevel.ADMIN, RiskLevel.DESTRUCTIVE},
        )
        return {"success": response.success, "message": response.message, "data": response.data}

    def _probe_event_bus(self):
        received: list[object] = []
        unsubscribe = self.events.subscribe("health.probe", received.append)
        try:
            self.events.publish("health.probe", source="watchdog")
            return len(received) == 1
        finally:
            unsubscribe()

    def _restart_companion(self) -> bool:
        self.companion.start()
        return bool(self.companion.snapshot().get("running", False))

    def _active_window_title(self) -> str | None:
        if self.windows is None:
            return None
        active = self.windows.active()
        return None if active is None else active.title

    def _authorize_capability(self, capability: Capability, permission_map: dict[Capability, str]) -> str:
        """Return the capability decision without collapsing confirmation into denial.

        The registry combines this decision with the action risk decision.  In
        particular, ``confirm`` means that the capability is available but the
        action must be staged in the registry's central confirmation queue.
        """
        if not self.mode.permits(capability.value):
            return "deny"
        return permission_decision(permission_map[capability])

    @staticmethod
    def _authorize_mission(action: str, arguments: dict, declared_risk: str) -> str:
        from action_guard import risk_level

        effective = risk_level(action)
        if effective == "denied" or str(declared_risk).lower() == "forbidden":
            return "deny"
        if effective != "safe" or str(declared_risk).lower() in {"sensitive", "admin", "destructive"}:
            return "confirm"
        return "allow"

    @staticmethod
    def _authorize_skill(manifest: SkillManifest, arguments: dict | None = None) -> str:
        if manifest.risk == "forbidden":
            return "deny"
        effective_risk = manifest.risk
        if manifest.name == "ruff.check" and bool((arguments or {}).get("fix")):
            effective_risk = "sensitive"
        if effective_risk in {"sensitive", "admin", "destructive"}:
            return "confirm"
        return "allow"


RUNTIME = CoreRuntime()
