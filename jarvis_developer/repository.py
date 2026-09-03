from __future__ import annotations
import ast
import hashlib
import os
import subprocess
import time
from collections import defaultdict
from pathlib import Path

EXCLUDED={".git","venv",".runtime-env",".python","dist","build","backups","data","__pycache__"}
class RepositoryAnalyzer:
    def __init__(self,root:Path,max_files:int=5000):self.root=Path(root).resolve();self.max_files=max_files
    def analyze(self)->dict:
        modules=[];issues=[];hashes=defaultdict(list);entrypoints=[]
        for index,path in enumerate(self.root.rglob("*.py")):
            if index>=self.max_files:break
            if any(part in EXCLUDED for part in path.relative_to(self.root).parts):continue
            relative=str(path.relative_to(self.root));text=path.read_text(encoding="utf-8",errors="replace");hashes[hashlib.sha256(text.encode()).hexdigest()].append(relative)
            try:tree=ast.parse(text,filename=relative)
            except SyntaxError as exc:issues.append({"file":relative,"line":exc.lineno,"error":exc.msg});continue
            symbols=[];imports=[]
            for node in tree.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):symbols.append({"name":node.name,"kind":type(node).__name__,"line":node.lineno})
                elif isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
                elif isinstance(node,ast.ImportFrom):imports.append(node.module or "")
                elif isinstance(node,ast.If) and isinstance(node.test,ast.Compare) and "__name__" in ast.unparse(node.test):entrypoints.append(relative)
            modules.append({"file":relative,"symbols":symbols,"imports":sorted(set(imports)),"lines":len(text.splitlines())})
        duplicates=[files for files in hashes.values() if len(files)>1]
        large=sorted((x for x in modules if x["lines"]>800),key=lambda x:x["lines"],reverse=True)
        return {"root":str(self.root),"modules":modules,"issues":issues,"entrypoints":sorted(set(entrypoints)),"duplicates":duplicates,"large_modules":large,"summary":{"python_files":len(modules),"syntax_issues":len(issues),"duplicate_groups":len(duplicates)}}

class TestRunner:
    __test__ = False
    def __init__(self,python_executable:Path):self.python=str(Path(python_executable).resolve())
    def run_unittest(self,root:Path,timeout:float=120)->dict:
        started=time.perf_counter();command=[self.python,"-m","unittest","discover","-s","tests","-v"];environment=os.environ.copy();environment["PYTHONNOUSERSITE"]="1";environment["PYTHONPATH"]=""
        try:result=subprocess.run(command,cwd=Path(root),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=max(1,min(float(timeout),600)),shell=False,env=environment)
        except subprocess.TimeoutExpired as exc:return {"successo":False,"timeout":True,"duration_ms":int((time.perf_counter()-started)*1000),"stdout":(exc.stdout or "")[-10000:],"stderr":(exc.stderr or "")[-10000:]}
        return {"successo":result.returncode==0,"timeout":False,"returncode":result.returncode,"duration_ms":int((time.perf_counter()-started)*1000),"stdout":result.stdout[-20000:],"stderr":result.stderr[-20000:],"command":command}
