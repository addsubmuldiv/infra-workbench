"""Transactional, application-owned user skill packages. No imported code executes."""
import base64
import copy
import hashlib
import io
import json
import posixpath
import re
import stat
import threading
import time
import uuid
import zipfile
from urllib.parse import unquote, urlsplit
from pathlib import Path

import yaml

UPLOAD_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 8 * 1024 * 1024
FILE_LIMIT = 1024 * 1024
COUNT_LIMIT = 128
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


class SkillError(ValueError):
    def __init__(self, message, status_code=400, code='INVALID_SKILL'):
        super().__init__(message)
        self.status_code, self.code = status_code, code


def safe_path(path):
    if not isinstance(path, str) or not path or len(path) > 240 or '\\' in path or ':' in path:
        raise SkillError('技能文件路径无效')
    parts = path.split('/')
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1,10)), *(f'lpt{i}' for i in range(1,10))}
    if any(p in ('', '.', '..') or p.endswith(('.', ' ')) or p.split('.')[0].lower() in reserved
           or any(ord(c)<32 or c in '<>"|?*' for c in p) for p in parts):
        raise SkillError('技能文件路径包含不允许的目录或名称')
    return path


def text_files(raw):
    result = {}
    for path, encoded in raw.items():
        data = base64.b64decode(encoded)
        try:
            text = data.decode('utf-8-sig')
            if '\x00' not in text:
                result[path] = text
        except UnicodeError:
            pass
    return result


def package_view(raw):
    """Decode each file once for both the text editor and manifest."""
    files, manifest = {}, []
    for path, encoded in raw.items():
        data=base64.b64decode(encoded)
        try:
            text=data.decode('utf-8-sig')
            if '\x00' not in text:files[path]=text
        except UnicodeError:pass
        manifest.append(dict(path=path,size=len(data),text=path in files))
    return dict(files=files,file_manifest=manifest)


def encode_files(files):
    if not isinstance(files, dict) or not files or len(files)>COUNT_LIMIT:
        raise SkillError('技能必须包含文件，最多 128 个')
    raw, seen, size, spellings, directories = {}, set(), 0, {}, set()
    for path, content in files.items():
        safe_path(path)
        parts=path.split('/')
        for index in range(1,len(parts)+1):
            prefix='/'.join(parts[:index]); folded=prefix.casefold()
            if folded in spellings and spellings[folded]!=prefix:raise SkillError('技能目录名称的大小写不一致')
            spellings[folded]=prefix
            if index<len(parts):directories.add(folded)
        if path.casefold() in seen: raise SkillError('技能文件名不能重复或仅大小写不同')
        seen.add(path.casefold())
        if not isinstance(content, (str, bytes)): raise SkillError('技能文件内容必须是文本')
        data = content.encode('utf-8') if isinstance(content, str) else content
        size += len(data)
        if len(data)>FILE_LIMIT or size>TOTAL_LIMIT: raise SkillError('技能文件超过大小限制')
        raw[path] = base64.b64encode(data).decode('ascii')
    if seen & directories:raise SkillError('技能文件与目录路径冲突')
    return raw


def parse_skill(files):
    text = files.get('SKILL.md', '')
    match = re.match(r'\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)\Z', text, re.S)
    if not match: raise SkillError('SKILL.md 需要 YAML 元数据和正文')
    # SafeLoader prevents object construction; block YAML aliases to bound expansion.
    if re.search(r'(^|\s)[&*][\w-]+',match[1]): raise SkillError('技能元数据不支持 YAML 锚点和别名')
    if len(match[1]) > 16384: raise SkillError('技能元数据超过 16 KiB')
    try:
        node = yaml.compose(match[1], Loader=yaml.SafeLoader)
        def check_keys(item, depth=0):
            if depth > 20: raise SkillError('技能元数据嵌套过深')
            if isinstance(item, yaml.MappingNode):
                seen=set()
                for key, value in item.value:
                    if not isinstance(key, yaml.ScalarNode) or key.value in seen: raise SkillError('技能元数据包含重复或非文本键')
                    seen.add(key.value);check_keys(value, depth+1)
            elif isinstance(item, yaml.SequenceNode):
                for value in item.value:check_keys(value, depth+1)
        check_keys(node)
        meta = yaml.safe_load(match[1])
    except (yaml.YAMLError, RecursionError): raise SkillError('SKILL.md 的 YAML 元数据格式无效') from None
    if not isinstance(meta,dict): raise SkillError('技能元数据必须是对象')
    name, description = meta.get('name'), meta.get('description')
    if not isinstance(name,str) or len(name)>64 or not NAME.fullmatch(name): raise SkillError('技能名称仅支持小写字母、数字和单个连字符，最多 64 字符')
    if not isinstance(description,str) or not description.strip() or len(description)>1024: raise SkillError('技能描述不能为空，最多 1024 字符')
    if not match[2].strip(): raise SkillError('技能正文不能为空')
    return meta


class SkillService:
    def __init__(self, store, builtin_root=None):
        self.store, self.db = store, store.db
        self.builtin_root = Path(builtin_root) if builtin_root is not None else Path(__file__).with_name('skills')
        if not hasattr(store, 'skill_lock'): store.skill_lock = threading.RLock()
        self.lock = store.skill_lock
        self._builtin_cache = None
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS user_skills (name TEXT PRIMARY KEY, incarnation TEXT NOT NULL, active INTEGER NOT NULL, enabled INTEGER NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS skill_versions (name TEXT NOT NULL, version INTEGER NOT NULL, incarnation TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(name,version))')
            self.db.execute('CREATE TABLE IF NOT EXISTS skill_drafts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def _builtins(self):
        paths=[]
        for entry in sorted(self.builtin_root.glob('*/SKILL.md')):
            paths.extend(p for p in sorted(entry.parent.rglob('*')) if p.is_file() and not p.is_symlink())
        signature=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in paths)
        if self._builtin_cache is not None and self._builtin_cache[0]==signature:
            return copy.deepcopy(self._builtin_cache[1])
        result = {}
        for path in sorted(self.builtin_root.glob('*/SKILL.md')):
            root = path.parent
            raw = encode_files({p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()})
            meta = parse_skill(text_files(raw))
            if meta['name'] != root.name: raise SkillError('内置技能名称与目录不一致')
            result[root.name] = self._payload(raw, meta, 1, 'builtin')
        self._builtin_cache=(signature,result)
        return copy.deepcopy(result)

    def _payload(self, raw, meta, version, source='user'):
        canonical = json.dumps(raw,sort_keys=True,separators=(',',':')).encode()
        return dict(name=meta['name'], description=meta['description'], version=version, source=source,
                    enabled=True, warnings=self._warnings(raw), created=time.time(), hash=hashlib.sha256(canonical).hexdigest(), raw=raw)

    def _warnings(self, raw):
        warnings=[]
        if any(p.startswith('scripts/') or p.endswith(('.py','.sh','.js','.ps1','.bat','.cmd')) for p in raw):
            warnings.append('技能包含脚本；当前运行环境不会执行脚本。')
        if len(text_files(raw)) != len(raw): warnings.append('包含二进制附件；可保存和导出，当前模型不会读取。')
        return warnings

    def _metadata(self, payload):
        return {k:v for k,v in payload.items() if k not in ('raw',)}

    def _current(self, name):
        return self.db.execute('SELECT incarnation,active,enabled FROM user_skills WHERE name=?',(name,)).fetchone()

    def _version(self, name, version):
        row = self.db.execute('SELECT payload FROM skill_versions WHERE name=? AND version=?',(name,version)).fetchone()
        if not row: raise SkillError('技能版本不存在',404,'SKILL_NOT_FOUND')
        return json.loads(row[0])

    def catalog(self):
        with self.lock:
            result=list(self._builtins().values())
            for name, active, enabled in self.db.execute('SELECT name,active,enabled FROM user_skills ORDER BY name').fetchall():
                payload=self._version(name,active);payload['enabled']=bool(enabled);result.append(payload)
            return sorted((self._metadata(p) for p in result),key=lambda p:p['name'])

    def read(self, name, version=None):
        with self.lock:
            builtins=self._builtins()
            if name in builtins:
                if version not in (None,1):raise SkillError('技能版本不存在',404)
                payload=builtins[name]; versions=[self._metadata(payload)]
            else:
                current=self._current(name)
                if not current:raise SkillError('技能不存在',404,'SKILL_NOT_FOUND')
                payload=self._version(name,version if version is not None else current[1])
                payload['enabled']=bool(current[2])
                versions=[self._metadata(json.loads(r[0])) for r in self.db.execute('SELECT payload FROM skill_versions WHERE name=? AND incarnation=? ORDER BY version DESC',(name,current[0])).fetchall()]
                if not any(v['version']==payload['version'] for v in versions):raise SkillError('此版本属于已卸载的技能',404)
            result=self._metadata(payload)
            result.update(package_view(payload['raw']),versions=versions)
            return result

    def snapshot(self):
        files, receipts={},[]
        with self.lock:
            for item in self.catalog():
                if not item['enabled']:continue
                detail=self.read(item['name'])
                files.update({f"/skills/{item['name']}/{p}":v for p,v in detail['files'].items()})
                receipts.append({k:item[k] for k in ('name','version','source')})
        return files,receipts

    def create_draft(self, files, skill_name=None, base_version=None):
        with self.lock:
            raw=encode_files(files)
            # Broken content may be saved as draft and repaired in the editor.
            try: parsed_name=parse_skill(text_files(raw))['name']
            except SkillError:parsed_name=None
            name=skill_name or parsed_name
            current=self._current(name) if name else None
            if skill_name is not None:
                if not current:raise SkillError('要更新的用户技能不存在',404)
                if base_version != current[1]:raise SkillError('技能版本已变化，请重新读取',409,'SKILL_CONFLICT')
                previous_raw=self._version(skill_name,base_version)['raw']
                previous_text=text_files(previous_raw)
                inherited={p:b for p,b in previous_raw.items() if p not in previous_text}
                inherited.update(raw)
                raw=encode_files({p:base64.b64decode(b) for p,b in inherited.items()})
            elif base_version is not None:raise SkillError('更新技能必须指定 skill_name')
            draft=dict(id=uuid.uuid4().hex,revision=1,skill_name=skill_name,base_version=base_version,
                       incarnation=current[0] if skill_name and current else None,created=time.time(),raw=raw)
            with self.db:self.db.execute('INSERT INTO skill_drafts VALUES (?,?)',(draft['id'],json.dumps(draft)))
            return self._draft_view(draft)

    def _draft(self, draft_id, revision=None):
        row=self.db.execute('SELECT payload FROM skill_drafts WHERE id=?',(draft_id,)).fetchone()
        if not row:raise SkillError('技能草稿不存在',404,'SKILL_NOT_FOUND')
        draft=json.loads(row[0])
        if revision is not None and draft['revision']!=revision:raise SkillError('草稿已修改，请重新读取',409,'SKILL_CONFLICT')
        return draft

    def _draft_view(self,draft):
        result={k:v for k,v in draft.items() if k not in ('raw','incarnation')}
        result.update(package_view(draft['raw']))
        return result

    def read_draft(self,draft_id):
        with self.lock:return self._draft_view(self._draft(draft_id))

    def list_drafts(self):
        with self.lock:
            result=[]
            for row in self.db.execute('SELECT payload FROM skill_drafts').fetchall():
                draft=json.loads(row[0])
                if draft.get('installed'):continue
                item={k:v for k,v in draft.items() if k not in ('raw','incarnation')}
                try:item['name']=parse_skill(text_files(draft['raw']))['name']
                except SkillError:item['name']=draft['skill_name'] or '未命名草稿'
                result.append(item)
            return sorted(result,key=lambda item:item['created'],reverse=True)

    def delete_draft(self,draft_id,expected_revision):
        with self.lock:
            self._draft(draft_id,expected_revision)
            with self.db:self.db.execute('DELETE FROM skill_drafts WHERE id=?',(draft_id,))
            return dict(id=draft_id,status='deleted')

    def update_draft(self,draft_id,revision,files):
        with self.lock:
            draft=self._draft(draft_id,revision)
            # The text editor cannot silently delete opaque binary attachments.
            previous_text=text_files(draft['raw'])
            raw={p:b for p,b in draft['raw'].items() if p not in previous_text}
            raw.update(encode_files(files))
            raw=encode_files({p:base64.b64decode(b) for p,b in raw.items()})
            draft.update(raw=raw,revision=revision+1)
            with self.db:self.db.execute('UPDATE skill_drafts SET payload=? WHERE id=?',(json.dumps(draft),draft_id))
            return self._draft_view(draft)

    def validate_draft(self,draft_id,revision,tools):
        with self.lock:
            draft=self._draft(draft_id,revision);errors=[];missing=[];raw=draft['raw'];files=text_files(raw)
            try:
                meta=parse_skill(files);name=meta['name']
                if name in self._builtins():errors.append('不能覆盖内置技能，请使用新名称')
                current=self._current(name)
                if draft['skill_name']:
                    if name!=draft['skill_name']:errors.append('更新技能不能修改名称；请新建技能')
                    if not current or current[0]!=draft['incarnation'] or current[1]!=draft['base_version']:errors.append('原技能已卸载或版本已变化，请重新创建草稿')
                elif current:errors.append('已有同名用户技能，请基于当前版本编辑')
                metadata=meta.get('metadata',{})
                if not isinstance(metadata,dict):errors.append('metadata 必须是对象')
                else:
                    required=metadata.get('workbench-required-tools', metadata.get('iwb-required-tools',''))
                    if not isinstance(required,str):errors.append('workbench-required-tools 必须是以空格分隔的工具名称')
                    else:missing=sorted(set(required.split())-set(tools));errors.extend(f'缺少工具：{n}' for n in missing)
                for path in set(re.findall(r'(?<![\w/])((?:references|assets|scripts)/[\w./-]+)',files['SKILL.md'])):
                    path=path.rstrip('.')
                    if path not in raw:errors.append('引用的技能文件不存在：'+path)
                for source,text in files.items():
                    if not source.lower().endswith('.md'):continue
                    links=re.findall(r'\]\(\s*(?:<([^>]+)>|([^\s)]+))',text)
                    for bracketed,plain in links:
                        target=bracketed or plain
                        try:parsed=urlsplit(target)
                        except ValueError:
                            errors.append('引用链接格式无效：'+target);continue
                        if parsed.scheme or parsed.netloc or not parsed.path:continue
                        resolved=posixpath.normpath(posixpath.join(posixpath.dirname(source),unquote(parsed.path)))
                        try:safe_path(resolved)
                        except SkillError:
                            errors.append('引用路径超出技能目录：'+target);continue
                        if resolved not in raw:errors.append('引用的技能文件不存在：'+resolved)
            except SkillError as exc:errors.append(str(exc))
            return dict(valid=not errors,errors=errors,warnings=self._warnings(raw),missing_tools=missing,revision=revision,
                        checks=dict(format=not errors,dependencies=not missing,execution='not_run'))

    def install_draft(self,draft_id,revision,tools):
        with self.lock:
            draft=self._draft(draft_id,revision)
            if draft.get('installed'):raise SkillError('此草稿已安装，请重新读取技能后编辑',409,'SKILL_CONFLICT')
            report=self.validate_draft(draft_id,revision,tools)
            if not report['valid']:raise SkillError('；'.join(report['errors']),409 if any('版本' in e or '同名' in e or '卸载' in e for e in report['errors']) else 400)
            meta=parse_skill(text_files(draft['raw']));name=meta['name']
            current=self._current(name)
            incarnation=current[0] if current else uuid.uuid4().hex
            version=self.db.execute('SELECT COALESCE(MAX(version),0)+1 FROM skill_versions WHERE name=?',(name,)).fetchone()[0]
            payload=self._payload(draft['raw'],meta,version)
            with self.db:
                self.db.execute('INSERT INTO skill_versions VALUES (?,?,?,?)',(name,version,incarnation,json.dumps(payload)))
                self.db.execute('INSERT OR REPLACE INTO user_skills VALUES (?,?,?,?)',(name,incarnation,version,1))
                draft['installed']=version
                self.db.execute('UPDATE skill_drafts SET payload=? WHERE id=?',(json.dumps(draft),draft_id))
            return dict(self._metadata(payload),status='installed',effective='next_turn',skill_id='user:'+name)

    def _mutable(self,name,expected_version):
        if name in self._builtins():raise SkillError('内置技能为只读；可以复制为新的用户技能',409)
        current=self._current(name)
        if not current:raise SkillError('用户技能不存在',404,'SKILL_NOT_FOUND')
        if current[1]!=expected_version:raise SkillError('技能版本已变化，请刷新后重试',409,'SKILL_CONFLICT')
        return current

    def set_enabled(self,name,enabled,expected_version):
        with self.lock:
            self._mutable(name,expected_version)
            with self.db:self.db.execute('UPDATE user_skills SET enabled=? WHERE name=?',(int(enabled),name))
            return dict(name=name,enabled=bool(enabled),version=expected_version,effective='next_turn')

    def rollback(self,name,version,expected_version):
        with self.lock:
            current=self._mutable(name,expected_version)
            if not self.db.execute('SELECT 1 FROM skill_versions WHERE name=? AND version=? AND incarnation=?',(name,version,current[0])).fetchone():raise SkillError('此技能历史版本不存在',404)
            with self.db:self.db.execute('UPDATE user_skills SET active=? WHERE name=?',(version,name))
            return dict(name=name,version=version,status='rolled_back',effective='next_turn')

    def delete(self,name,expected_version):
        with self.lock:
            self._mutable(name,expected_version)
            with self.db:self.db.execute('DELETE FROM user_skills WHERE name=?',(name,))
            return dict(name=name,status='deleted',effective='next_turn')

    def import_package(self,filename,content):
        if len(content)>UPLOAD_LIMIT:raise SkillError('导入文件不能超过 2 MiB')
        if filename.lower().endswith('.md'):
            try: text=content.decode('utf-8-sig')
            except UnicodeError:raise SkillError('Markdown 文件必须是 UTF-8 文本') from None
            return self.create_draft({'SKILL.md':text})
        if not filename.lower().endswith('.zip'):raise SkillError('请选择 Markdown 或 ZIP 文件')
        raw={};seen=set();total=0
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos=archive.infolist()
                if len(infos)>COUNT_LIMIT*2:raise SkillError('归档条目过多')
                for info in infos:
                    path=info.filename.rstrip('/') if info.is_dir() else info.filename
                    safe_path(path)
                    if path.casefold() in seen:raise SkillError('归档中有重复或大小写冲突的路径')
                    seen.add(path.casefold())
                    mode=(info.external_attr>>16)&0o170000
                    if mode not in (0,stat.S_IFREG,stat.S_IFDIR):raise SkillError('归档不允许符号链接或特殊文件')
                    if info.flag_bits&1:raise SkillError('不支持加密 ZIP')
                    if info.is_dir():continue
                    total+=info.file_size
                    if info.file_size>FILE_LIMIT or total>TOTAL_LIMIT or len(raw)>=COUNT_LIMIT:raise SkillError('归档解压后超过大小或文件数量限制')
                    with archive.open(info) as stream:data=stream.read(FILE_LIMIT+1)
                    if len(data)>FILE_LIMIT:raise SkillError('归档文件超过大小限制')
                    raw[path]=data
        except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError):raise SkillError('ZIP 文件损坏或格式不支持') from None
        roots=[p for p in raw if p=='SKILL.md' or p.endswith('/SKILL.md')]
        if len(roots)!=1:raise SkillError('ZIP 必须恰好包含一个 SKILL.md')
        prefix=roots[0][:-len('SKILL.md')]
        if any(not p.startswith(prefix) for p in raw):raise SkillError('ZIP 中所有文件必须位于同一个技能目录')
        normalized={p[len(prefix):]:data for p,data in raw.items()}
        if prefix:
            try:meta=parse_skill({p:data.decode('utf-8-sig') for p,data in normalized.items() if p=='SKILL.md'})
            except UnicodeError:raise SkillError('SKILL.md 必须为 UTF-8 文本') from None
            if prefix.rstrip('/').split('/')[-1]!=meta['name']:raise SkillError('技能目录名必须与 name 一致')
        return self.create_draft(normalized)

    def export(self,name,version=None):
        with self.lock:
            detail=self.read(name,version)
            payload=self._builtins()[name] if detail['source']=='builtin' else self._version(name,detail['version'])
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
                for path,data in payload['raw'].items():archive.writestr(name+'/'+path,base64.b64decode(data))
            return out.getvalue()
