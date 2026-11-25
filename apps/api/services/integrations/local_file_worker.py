"""Isolated untrusted compressed-file parser. No app configuration or DB access."""
import sys,json
def main():
    if len(sys.argv)!=2 or sys.argv[1] not in (".pdf",".xlsx"):return 2
    if sys.platform!="win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    try:
        from apps.api.services.integrations.local_files import LocalFilesAdapter
        data=sys.stdin.buffer.read(10*1024*1024+1)
        if not 1<=len(data)<=10*1024*1024:return 2
        parsed=LocalFilesAdapter._extract(data,"source"+sys.argv[1])
        encoded=json.dumps(parsed,ensure_ascii=True,default=str).encode()
        if len(encoded)>8*1024*1024:return 2
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception:
        return 2
if __name__=="__main__":sys.exit(main())
