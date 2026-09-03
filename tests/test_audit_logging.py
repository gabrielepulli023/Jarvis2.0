import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import audit_log
from jarvis_core.logging import JsonFormatter
import logging

class AuditLoggingTests(unittest.TestCase):
    def test_action_schema_and_recursive_secret_redaction(self):
        root=Path(tempfile.mkdtemp())/"audit.jsonl"
        with patch.object(audit_log,"LOG_PATH",root):
            audit_log.record_action(request_id="r",user_command="x",planner_decision="p",tool="t",arguments={"api_key":"secret"},risk="safe",permission="allow",result={"token":"hidden"},duration_ms=2,verification="ok")
        row=json.loads(root.read_text(encoding="utf-8"));self.assertEqual(row["arguments"]["api_key"],"[REDACTED]");self.assertEqual(row["result"]["token"],"[REDACTED]")
    def test_json_formatter_redacts_message_and_nested_extra(self):
        record=logging.LogRecord("x",logging.INFO,"",1,"password=hunter2",(),None);record.payload={"authorization":"Bearer abc"}
        row=json.loads(JsonFormatter().format(record));self.assertNotIn("hunter2",json.dumps(row));self.assertEqual(row["payload"]["authorization"],"[REDACTED]")

if __name__=="__main__":unittest.main()
