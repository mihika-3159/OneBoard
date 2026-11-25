"""Linux operator-side encrypted backup scheduler, retention and replica contract.

Run via the supplied systemd timer. Neither the API nor this module signs up
for storage. Directory replica is a simulated independent-storage adapter,
not evidence of physical offsite storage.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,tempfile,time
from typing import Protocol
from scripts.operations.backup_encrypted import backup,verify_manifest

NAME=re.compile(r"oneboard-\d{8}T\d{6}Z-[a-f0-9]{8}\.dump\.age")
MAX_FILES=10000
def utcnow():return datetime.now(timezone.utc)
def timestamp(value):
    result=datetime.fromisoformat(value)
    if result.tzinfo is None:raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)
def private_dir(directory):
    p=Path(directory)
    if not p.is_dir() or p.is_symlink() or p.stat().st_mode&0o077:
        raise RuntimeError("Private non-symlink directory required")
    return p.resolve()
def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def atomic_json(path,record):
    path=Path(path)
    if path.is_symlink():raise RuntimeError("Unsafe state file")
    fd,name=tempfile.mkstemp(prefix=".state-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as h:
            json.dump(record,h,sort_keys=True,allow_nan=False);h.flush();os.fsync(h.fileno())
        os.replace(name,path);sync_directory(path.parent)
    finally:Path(name).unlink(missing_ok=True)
@contextmanager
def exclusive(directory):
    # systemd timer and manual invocation share a process/crash-safe lock.
    import fcntl
    fd=os.open(directory/".backup.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)
def inventory(directory):
    entries=[]
    for index,p in enumerate(directory.iterdir()):
        if index>=MAX_FILES:raise RuntimeError("Backup directory inventory limit exceeded")
        if NAME.fullmatch(p.name):
            if p.is_symlink():raise RuntimeError("Unsafe backup entry")
            manifest=p.with_name(p.name+".json")
            record=verify_manifest(p,manifest)
            date=timestamp(record["created_utc"])
            if date>utcnow()+timedelta(minutes=5):raise RuntimeError("Future backup timestamp")
            entries.append((date,p,manifest,record))
        elif p.name.endswith(".dump.age.json") and NAME.fullmatch(p.name[:-5]):
            if not p.with_name(p.name[:-5]).is_file():raise RuntimeError("Orphan backup manifest; operator review required")
    return sorted(entries,key=lambda x:(x[0],x[1].name),reverse=True)
class BackupStorage(Protocol):
    def put(self,archive:Path,manifest:Path)->None: ...
    def verify(self,name:str,sha256:str)->None: ...
    def retrieve(self,name:str,destination:Path)->tuple[Path,Path]: ...
class DirectoryReplica:
    """Simulated adapter. Copies only encrypted bytes and metadata."""
    def __init__(self,root,primary):
        self.root=private_dir(root);primary=private_dir(primary)
        if self.root==primary or self.root in primary.parents or primary in self.root.parents:
            raise ValueError("Replica must be a separate directory tree")
    def _path(self,name):
        if not NAME.fullmatch(name):raise ValueError("Invalid backup object name")
        return self.root/name
    def _copy(self,source,dest):
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or not dest.is_file():raise ValueError("Unsafe replica object")
            # Existing object is immutable; verify pair separately.
            return
        fd,temp=tempfile.mkstemp(prefix=".replica-",dir=dest.parent)
        try:
            with os.fdopen(fd,"wb") as out,source.open("rb") as src:
                shutil.copyfileobj(src,out,1024*1024);out.flush();os.fsync(out.fileno())
            os.link(temp,dest,follow_symlinks=False);sync_directory(dest.parent)
        finally:Path(temp).unlink(missing_ok=True)
    def put(self,archive,manifest):
        record=verify_manifest(archive,manifest);target=self._path(archive.name)
        self._copy(archive,target);self._copy(manifest,target.with_name(target.name+".json"))
        self.verify(archive.name,record["sha256"])
    def verify(self,name,sha256):
        p=self._path(name);record=verify_manifest(p,p.with_name(name+".json"))
        if record["sha256"]!=sha256:raise RuntimeError("Replica differs from source")
    def retrieve(self,name,destination):
        source=self._path(name);dest=private_dir(destination)
        target=dest/name;manifest=target.with_name(name+".json")
        record=verify_manifest(source,source.with_name(name+".json"))
        self._copy(source,target);self._copy(source.with_name(name+".json"),manifest)
        if verify_manifest(target,manifest)["sha256"]!=record["sha256"]:raise RuntimeError("Retrieved replica differs")
        return target,manifest
def expiration_plan(entries,now,days,keep):
    if not 7<=days<=3650 or not 2<=keep<=1000:raise ValueError("Unsafe retention policy")
    return [e for e in entries[keep:] if e[0]<now-timedelta(days=days)]
def expire(entries,now,days,keep,replica=None):
    # Require an independently verified copy before expiration when configured.
    # Local and replica inventories have separate retention responsibility.
    victims=expiration_plan(entries,now,days,keep)
    for _,archive,manifest,record in victims:
        verify_manifest(archive,manifest)
        if replica is not None:replica.verify(archive.name,record["sha256"])
    for _,archive,manifest,_ in victims:
        archive.unlink();manifest.unlink();sync_directory(archive.parent)
    return len(victims)
def manage(directory,recipient,source,interval_hours=24,retention_days=30,keep=3,replica=None,now=None,min_free_mib=256):
    if not 1<=interval_hours<=168 or not 1<=min_free_mib<=1048576:raise ValueError("Invalid backup schedule or disk floor")
    if source.get("ONEBOARD_BACKUP_OPERATION_APPROVED")!="YES" or source.get("ONEBOARD_PRODUCTION_MODE","").lower() not in ("1","true"):
        raise RuntimeError("Explicit backup operation approval required")
    directory=private_dir(directory);now=now or utcnow()
    expiration_plan([],now,retention_days,keep)
    with exclusive(directory):
        state_path=directory/"backup-status.json"
        report={"checked_at":now.isoformat(),"status":"failed","replica_mode":"simulated_directory" if replica else "none","offsite_verified":False}
        try:
            entries=inventory(directory)
            due=not entries or now-entries[0][0]>=timedelta(hours=interval_hours)
            if due:
                if shutil.disk_usage(directory).free<min_free_mib*1048576:raise RuntimeError("Insufficient backup disk capacity")
                archive,manifest=backup(directory,recipient,source)
                entries=inventory(directory)
            if replica:
                for _,archive,manifest,_ in entries:replica.put(archive,manifest)
            expired=expire(entries,now,retention_days,keep,replica)
            entries=inventory(directory)
            report.update(status="ok",backup_created=due,expired=expired,verified_archives=len(entries),latest_backup_utc=entries[0][0].isoformat(),
                recovery_point_age_upper_bound_seconds=max(0,(now-timestamp(entries[0][3].get("snapshot_started_utc",entries[0][3]["created_utc"]))).total_seconds()),
                ciphertext_integrity_verified=True,restore_verified=False)
        except Exception as exc:
            report.update(error_type=type(exc).__name__,alert="backup_integrity_or_execution_failed")
            atomic_json(state_path,report)
            raise RuntimeError("Backup management failed; inspect local status and inventory") from None
        atomic_json(state_path,report)
        return report
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory",type=Path,required=True);p.add_argument("--recipient",required=True)
    p.add_argument("--interval-hours",type=int,default=24);p.add_argument("--retention-days",type=int,default=30)
    p.add_argument("--keep",type=int,default=3);p.add_argument("--replica-directory",type=Path)
    p.add_argument("--min-free-mib",type=int,default=256);a=p.parse_args()
    replica=DirectoryReplica(a.replica_directory,a.directory) if a.replica_directory else None
    print(json.dumps(manage(a.directory,a.recipient,os.environ,a.interval_hours,a.retention_days,a.keep,replica,min_free_mib=a.min_free_mib),sort_keys=True))
if __name__=="__main__":main()
