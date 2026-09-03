from __future__ import annotations
import json
import re
from pathlib import Path

class UniversalSearch:
    """Bounded local search across memory, missions, skills, logs and project text."""
    TEXT_SUFFIXES={".py",".md",".txt",".json",".toml",".yaml",".yml",".ini",".cfg",".js",".html",".css"}
    EXCLUDED={".git","venv",".runtime-env",".python","dist","build","backups","__pycache__"}
    def __init__(self,root:Path,memory,missions,data_root:Path):self.root=Path(root).resolve();self.memory=memory;self.missions=missions;self.data_root=Path(data_root)
    def search(self,query:str,limit:int=30)->list[dict]:
        value=str(query).strip()
        if not value:return []
        tokens=[x for x in re.findall(r"\w+",value.lower()) if len(x)>1];results=[]
        for row in self.memory.search(value,limit=limit):results.append({"source":"memory","score":row["score"],"title":row["kind"],"content":row["content"],"ref":row["id"]})
        for row in self.missions.recent(100):
            score=self._score(tokens,f"{row['objective']} {row['status']}")
            if score:results.append({"source":"mission","score":score,"title":row["status"],"content":row["objective"],"ref":row["id"]})
        results.extend(self._search_json(self.data_root/"jarvis_skills.json",tokens,"skill"))
        results.extend(self._search_logs(self.data_root/"logs"/"jarvis.jsonl",tokens))
        results.extend(self._search_files(tokens,max_files=1500,max_bytes=1_000_000))
        results.sort(key=lambda x:(x["score"],x["source"]),reverse=True);return results[:max(1,min(int(limit),100))]
    @staticmethod
    def _score(tokens:list[str],text:str)->float:
        lower=text.lower();return 0 if not tokens else sum(token in lower for token in tokens)/len(tokens)
    def _search_json(self,path:Path,tokens:list[str],source:str)->list[dict]:
        if not path.exists():return []
        try:data=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):return []
        rows=data.values() if isinstance(data,dict) else data if isinstance(data,list) else []
        found=[]
        for index,row in enumerate(rows):
            text=json.dumps(row,ensure_ascii=False);score=self._score(tokens,text)
            if score:found.append({"source":source,"score":score,"title":str(row.get("name",source)) if isinstance(row,dict) else source,"content":text[:1000],"ref":str(index)})
        return found
    def _search_logs(self,path:Path,tokens:list[str])->list[dict]:
        if not path.exists():return []
        try:lines=path.read_text(encoding="utf-8",errors="replace").splitlines()[-2000:]
        except OSError:return []
        return [{"source":"log","score":score,"title":"log","content":line[:1000],"ref":str(path)} for line in lines if (score:=self._score(tokens,line))]
    def _search_files(self,tokens:list[str],max_files:int,max_bytes:int)->list[dict]:
        found=[];seen=0
        for path in self.root.rglob("*"):
            if seen>=max_files:break
            if not path.is_file() or path.suffix.lower() not in self.TEXT_SUFFIXES or any(part in self.EXCLUDED for part in path.parts):continue
            seen+=1
            try:
                if path.stat().st_size>max_bytes:continue
                text=path.read_text(encoding="utf-8",errors="replace")
            except OSError:continue
            score=self._score(tokens,f"{path.name} {text}")
            if score:
                line=next((x.strip() for x in text.splitlines() if self._score(tokens,x)>0),"")
                found.append({"source":"file","score":score,"title":path.name,"content":line[:1000],"ref":str(path)})
        return found
