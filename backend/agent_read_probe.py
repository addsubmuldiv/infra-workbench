"""Fixed read-only operations; composed with existing file/process readers over SSH."""
import importlib.metadata
import selectors
import subprocess
import sys
import time


def check_command(argv):
    """Drain a bounded pipe with a total deadline; never invoke a shell."""
    child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,shell=False)
    output=bytearray();deadline=time.monotonic()+5;truncated=False;timed_out=False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout,selectors.EVENT_READ)
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    timed_out=True;break
                if not selector.select(remaining):
                    timed_out=True;break
                chunk=os.read(child.stdout.fileno(),min(8192,65537-len(output)))
                if not chunk:break
                output.extend(chunk)
                if len(output)>65536:
                    truncated=True;break
        if timed_out or truncated:child.kill()
        code=child.wait(timeout=1)
    finally:
        if child.poll() is None:
            child.kill();child.wait()
        child.stdout.close()
    return dict(exit_code=code,stdout=bytes(output[:65536]).decode('utf-8',errors='replace'),
                truncated=truncated,timed_out=timed_out)


def agent_read(request):
    action=request['action']
    if action=='read_directory':
        path=checked_path(request['path'])
        offset=request.get('offset',0)
        listing=browse(path,offset,100)
        # Preserve a usable cursor instead of cutting JSON halfway through a page.
        while len(listing['entries'])>1 and len(json.dumps(listing,ensure_ascii=False))>4500:
            listing['entries'].pop()
            listing['next_offset']=offset+len(listing['entries'])
        listing['truncated']=listing['next_offset'] is not None
        return dict(ok=True,result=listing,command='读取目录',cwd=os.getcwd())
    if action=='read_file':
        path=checked_path(request['path'])
        content,raw,_,revision=text_file(path)
        lines=content.splitlines();start=request.get('start_line',1);limit=request.get('max_lines',100)
        selected=lines[start-1:start-1+limit]
        text='\n'.join(selected)
        return dict(ok=True,result=dict(path=path,start_line=start,end_line=start+len(selected)-1,total_lines=len(lines),
                    content=text[:16000],truncated=start-1+len(selected)<len(lines) or len(text)>16000,revision=revision,bytes=len(raw)),
                    command='读取文本文件',cwd=os.getcwd())
    if action=='system':
        argv=['uname','-a']
    elif action=='ports':
        argv=['ss','-H','-ltnp']
    elif action=='disk':
        argv=['df','-h','--',checked_path(request.get('path','~'))]
    elif action=='processes':
        if request.get('pid'):
            pid=request['pid']
            try:cutoff=int(float(read_text('/proc/uptime').split()[0])*os.sysconf('SC_CLK_TCK'))
            except (ValueError,IndexError,OSError):cutoff=None
            return dict(ok=True,result=read_process_details(pid,process_cutoff_ticks=cutoff),
                        command='读取指定 PID 的只读进程信息',cwd=os.getcwd(),exit_code=0)
        argv=['ps','-eo','pid,ppid,user,etime,comm','--no-headers']
    elif action=='environment':
        packages={}
        for name in ('torch','torch-npu','vllm','sglang','transformers'):
            try:packages[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:packages[name]=None
        return dict(ok=True,result=dict(python=sys.version,executable=sys.executable,packages=packages,
                    variables={name:os.environ.get(name) for name in ('CUDA_VISIBLE_DEVICES','ASCEND_RT_VISIBLE_DEVICES','PYTHONPATH','LD_LIBRARY_PATH')}),
                    command='读取 Python 版本、包元数据和设备相关环境变量',cwd=os.getcwd(),exit_code=0)
    elif action=='tmux':
        return dict(ok=True,result=tmux_sessions(),command='tmux list-sessions',cwd=os.getcwd(),exit_code=0)
    else:
        raise ValueError('不支持的只读检查；没有执行远端命令')
    result=check_command(argv)
    if action=='ports' and request.get('port'):
        result['stdout']='\n'.join(line for line in result['stdout'].splitlines()
            if any(re.search(r':'+str(request['port'])+r'$',field) for field in line.split()[3:5]))
    return dict(ok=result['exit_code']==0 and not result['timed_out'],command=' '.join(argv),cwd=os.getcwd(),**result)


def agent_read_main(request):
    try:
        result=agent_read(request)
    except PermissionError:result=dict(ok=False,error='当前 SSH 账号没有读取权限')
    except FileNotFoundError:result=dict(ok=False,error='路径不存在，或该检查命令未安装')
    except (NotADirectoryError,IsADirectoryError):result=dict(ok=False,error='路径类型不符合操作要求')
    except ValueError as exc:result=dict(ok=False,error=str(exc))
    except OSError:result=dict(ok=False,error='远端读取失败，请检查路径、权限或检查工具')
    print('IWB_AGENT:'+json.dumps(result,ensure_ascii=True))
