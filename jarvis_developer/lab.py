from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

EXCLUDED={".git","venv",".runtime-env",".python","dist","build","backups","data","__pycache__"}
def _safe(root:Path,relative:str)->Path:
    value=Path(str(relative).replace("\\","/"))
    if value.is_absolute() or ".." in value.parts:raise ValueError(f"unsafe relative path: {relative}")
    target=(root/value).resolve()
    try:target.relative_to(root.resolve())
    except ValueError:raise ValueError(f"path escapes workspace: {relative}") from None
    return target
def _digest(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()

class PatchTransaction:
    def __init__(self,root:Path,transactions_root:Path):
        self.root=Path(root).resolve();self.id=uuid.uuid4().hex[:16];self.backup=Path(transactions_root)/self.id;self.backup.mkdir(parents=True,exist_ok=False);self._records=[];self._closed=False
    def write(self,relative:str,content:str)->Path:
        if self._closed:raise RuntimeError("transaction is closed")
        target=_safe(self.root,relative);existed=target.exists();backup=self.backup/relative
        if not any(x["relative"]==relative for x in self._records):
            if existed:backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
            self._records.append({"relative":relative,"existed":existed,"before":_digest(target) if existed else None})
        target.parent.mkdir(parents=True,exist_ok=True);handle,temp_name=tempfile.mkstemp(prefix=target.name+".",suffix=".tmp",dir=target.parent);os.close(handle);temp=Path(temp_name)
        try:temp.write_text(str(content),encoding="utf-8");os.replace(temp,target)
        finally:temp.unlink(missing_ok=True)
        return target
    def commit(self)->dict:
        if self._closed:raise RuntimeError("transaction is closed")
        manifest={"id":self.id,"status":"committed","created_at":time.time(),"root":str(self.root),"files":[{**row,"after":_digest(_safe(self.root,row["relative"]))} for row in self._records]};(self.backup/"transaction.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8");self._closed=True;return manifest
    def rollback(self)->dict:
        restored=[]
        for row in reversed(self._records):
            target=_safe(self.root,row["relative"]);backup=self.backup/row["relative"]
            if row["existed"]:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup,target)
            else:target.unlink(missing_ok=True)
            restored.append(row["relative"])
        self._closed=True;(self.backup/"rollback.json").write_text(json.dumps({"id":self.id,"restored":restored,"at":time.time()},indent=2),encoding="utf-8");return {"id":self.id,"restored":restored}
    @staticmethod
    def restore_committed(root:Path,transaction_directory:Path)->dict:
        directory=Path(transaction_directory);manifest=json.loads((directory/"transaction.json").read_text(encoding="utf-8"));restored=[]
        for row in reversed(manifest["files"]):
            target=_safe(Path(root).resolve(),row["relative"]);backup=directory/row["relative"]
            if row["existed"]:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup,target)
            else:target.unlink(missing_ok=True)
            restored.append(row["relative"])
        return {"id":manifest["id"],"restored":restored}

class LabWorkspace:
    def __init__(self,live_root:Path,lab_root:Path,transactions_root:Path):self.live=Path(live_root).resolve();self.lab_root=Path(lab_root);self.transactions_root=Path(transactions_root);self.path=None
    def create(self)->Path:
        identity=f"lab_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}";target=self.lab_root/identity
        def ignore(directory,names):return [name for name in names if name in EXCLUDED]
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(self.live,target,ignore=ignore);self.path=target;return target
    def transaction(self)->PatchTransaction:
        if self.path is None:raise RuntimeError("LAB has not been created")
        return PatchTransaction(self.path,self.transactions_root/"lab")
    def promote(self,relative_paths:list[str],validator)->dict:
        if self.path is None:raise RuntimeError("LAB has not been created")
        validation=validator(self.path)
        if not validation.get("success",validation.get("successo",False)):return {"successo":False,"messaggio":"Validazione LAB fallita.","validation":validation}
        transaction=PatchTransaction(self.live,self.transactions_root/"live")
        try:
            for relative in relative_paths:
                source=_safe(self.path,relative)
                if not source.is_file():raise FileNotFoundError(relative)
                transaction.write(relative,source.read_text(encoding="utf-8"))
            manifest=transaction.commit();return {"successo":True,"messaggio":"Promozione LAB completata con rollback disponibile.","transaction":manifest}
        except Exception:
            transaction.rollback();raise
