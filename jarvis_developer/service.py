from __future__ import annotations
import threading
import uuid
from pathlib import Path
from .lab import LabWorkspace,PatchTransaction
from .repository import RepositoryAnalyzer,TestRunner
from jarvis_core.logging import redact

class DeveloperService:
    def __init__(self,live_root:Path,data_root:Path,python_executable:Path):self.live=Path(live_root).resolve();self.data=Path(data_root);self.analyzer=RepositoryAnalyzer(self.live);self.tests=TestRunner(python_executable);self._labs={};self._lock=threading.RLock()
    def inspect(self)->dict:return self.analyzer.analyze()
    def create_lab(self)->dict:
        lab=LabWorkspace(self.live,self.data/"labs",self.data/"transactions");path=lab.create();identity=uuid.uuid4().hex[:12]
        with self._lock:self._labs[identity]=lab
        return {"successo":True,"id":identity,"path":str(path)}
    def patch(self,lab_id:str,files:list[dict])->dict:
        with self._lock:lab=self._labs.get(lab_id)
        if not lab:return {"successo":False,"messaggio":"LAB non trovato."}
        transaction=lab.transaction()
        try:
            for row in files:transaction.write(str(row["path"]),str(row["content"]))
            return {"successo":True,"transaction":transaction.commit(),"files":[str(x["path"]) for x in files]}
        except Exception as exc:transaction.rollback();return {"successo":False,"messaggio":redact(f"{type(exc).__name__}: {exc}")}
    def test(self,lab_id:str,timeout:float=120)->dict:
        with self._lock:lab=self._labs.get(lab_id)
        if not lab or lab.path is None:return {"successo":False,"messaggio":"LAB non trovato."}
        return self.tests.run_unittest(lab.path,timeout)
    def promote(self,lab_id:str,paths:list[str],timeout:float=120)->dict:
        with self._lock:lab=self._labs.get(lab_id)
        if not lab:return {"successo":False,"messaggio":"LAB non trovato."}
        return lab.promote(paths,lambda root:self.tests.run_unittest(root,timeout))
    def rollback_live(self,transaction_id:str)->dict:
        directory=self.data/"transactions"/"live"/transaction_id
        if not (directory/"transaction.json").is_file():return {"successo":False,"messaggio":"Transazione non trovata."}
        result=PatchTransaction.restore_committed(self.live,directory);return {"successo":True,"messaggio":"Rollback completato.","dati":result}
