"""Bounded in-memory Excel parsing. Public rows never contain passwords."""
import io
import re
import zipfile
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from pydantic import SecretStr

MAX_FILE=2*1024*1024
MAX_ROWS=100
HEADERS={
    'target':{'ip','ip地址','服务器ip','主机地址','服务器地址','地址','host','hostname','ssh别名','别名','主机'},
    'user':{'账号','帐号','用户名','账户','user','username','account'},
    'password':{'密码','口令','password','pwd'},
    'port':{'端口','ssh端口','port','sshport'},
}

class WorkbookError(ValueError):
    """An intentional, non-sensitive workbook validation message."""


@dataclass(repr=False)
class ImportRow:
    row:int
    target:str
    user:str
    port:int=22
    password:SecretStr|None=field(default=None,repr=False)
    status:str='ready'
    reason:str=''
    host_id:str|None=None
    key_status:str='not_requested'
    key_reason:str=''
    password_status:str='not_provided'
    password_reason:str=''
    expected_identity:str|None=field(default=None,repr=False)

    def __post_init__(self):
        if isinstance(self.password,str):self.password=SecretStr(self.password)
        if self.password:self.password_status='pending'

    def view(self):
        return dict(row=self.row,target=self.target,user=self.user,port=self.port,status=self.status,
                    reason=self.reason,host_id=self.host_id,key_status=self.key_status,key_reason=self.key_reason,
                    password_status=self.password_status,password_reason=self.password_reason)


def parse_workbook(data):
    if not data or len(data)>MAX_FILE:raise WorkbookError('文件不能为空，且不能超过 2 MiB')
    book=None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(x.file_size for x in entries)>16*1024*1024:
                raise WorkbookError('Excel 解压后过大，请只保留服务器列表')
        book=load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
        sheet=book.worksheets[0]
        if (sheet.max_row or 0)>1001 or (sheet.max_column or 0)>32:
            raise WorkbookError('请只保留服务器列表：最多 100 台，表格不超过 1000 行、32 列')
        # Some producers write an incorrect dimension. Count actual rows and
        # stop at the limit instead of trusting a smaller reported range.
        sheet.reset_dimensions()
        iterator=sheet.iter_rows(max_col=33)
        header=next(iterator,[]);columns={}
        for index,cell in enumerate(header):
            if index>=32 and cell.value not in (None,''):raise WorkbookError('表格不超过 32 列')
            value=re.sub(r'[\s_\-]+','',str(cell.value or '').lstrip('\ufeff')).lower()
            key=next((key for key,names in HEADERS.items() if value in names),None)
            if key:
                if key in columns:raise WorkbookError('表头存在重复字段，请每种字段只保留一列')
                columns[key]=index
        if not {'target','user'}<=columns.keys():raise WorkbookError('首行必须包含 IP 和账号列，可选密码、端口列')
        rows=[];seen={}
        for number,cells in enumerate(iterator,2):
            if number>1001:raise WorkbookError('表格不超过 1000 行，请删除多余空行或拆分文件')
            if cells[32].value not in (None,''):raise WorkbookError('表格不超过 32 列')
            if all(cell.value in (None,'') for cell in cells):continue
            if len(rows)>=MAX_ROWS:raise WorkbookError('一次最多导入 100 台服务器，请拆分表格')
            values={key:cells[index] for key,index in columns.items()}
            target=values['target'].value;user=values['user'].value
            row=ImportRow(number,str(target or '').strip(),str(user or '').strip())
            try:
                if any(cell.data_type in ('f','e') for cell in values.values()):raise ValueError('不支持公式或错误值，请先粘贴为纯文本或数值')
                if not isinstance(target,str) or not re.fullmatch(r'[\w.@:+-]+',row.target) or row.target.startswith('-') or len(row.target)>253:
                    raise ValueError('IP / 主机地址格式不正确')
                if not row.user or not re.fullmatch(r'[\w.@:+-]+',row.user) or row.user.startswith('-') or len(row.user)>100:
                    raise ValueError('账号为空或格式不正确')
                port=values['port'].value if 'port' in values else None
                if port not in (None,''):
                    if isinstance(port,bool) or not re.fullmatch(r'\d{1,5}',str(port).strip()):raise ValueError('端口必须为 1–65535 的整数')
                    row.port=int(str(port).strip())
                    if not 1<=row.port<=65535:raise ValueError('端口必须为 1–65535 的整数')
                password=values['password'].value if 'password' in values else None
                if password not in (None,''):
                    if isinstance(password,int) and values['password'].number_format not in ('General','0','@'):
                        raise ValueError('密码使用了数字显示格式，请将密码单元格设为文本并重新填写，避免前导零等内容丢失')
                    if isinstance(password,bool) or not isinstance(password,(str,int)) or (isinstance(password,int) and len(str(password))>15):
                        raise ValueError('密码格式无法准确读取，请将密码单元格设为文本后重新填写')
                    if len(str(password))>4096:raise ValueError('密码过长')
                    row.password=SecretStr(str(password))
                    row.password_status='pending'
                identity=(row.target.lower(),row.user,row.port)
                if identity in seen:
                    row.status='skipped';row.reason=f'与文件第 {seen[identity]} 行重复，已跳过';row.password=None
                    if row.password_status=='pending':row.password_status='not_saved';row.password_reason='重复记录，未保存本行密码'
                else:seen[identity]=number
            except ValueError as exc:
                row.status='invalid';row.reason=str(exc);row.password=None
                if row.password_status=='pending':row.password_status='not_saved';row.password_reason='记录格式错误，未保存本行密码'
            rows.append(row)
        if not rows:raise WorkbookError('表格没有服务器记录，请在表头下填写服务器信息')
        return rows
    except WorkbookError:raise
    except Exception:raise WorkbookError('无法读取 Excel，请使用未加密的 .xlsx 文件，首行为表头') from None
    finally:
        if book is not None:book.close()


def import_template():
    book=Workbook();sheet=book.active;sheet.title='服务器列表'
    sheet.append(['IP','账号','密码','端口'])
    sheet.append(['192.0.2.10','your_user','replace_with_password',22])
    sheet.append(['192.0.2.11','your_user',None,22])
    for row in sheet:
        for cell in row:cell.font=Font(name='Arial',size=11)
    for cell in sheet[1]:cell.font=Font(name='Arial',size=11,bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='28766E')
    for column,width in [('A',27),('B',23),('C',32),('D',14)]:sheet.column_dimensions[column].width=width
    for row in sheet.iter_rows(min_row=2,max_row=101,max_col=3):
        for cell in row:cell.number_format='@'
    sheet.freeze_panes='A2';sheet.auto_filter.ref='A1:D3'
    notes=book.create_sheet('填写说明')
    for text in ['请替换示例 IP、账号、密码；删除不用的示例行。','程序只读取第一个工作表，首行为表头。','IP 和账号必填；IP 列也可填写已有机器的 SSH 别名。密码留空时使用已有免密；端口留空默认为 22，非标准端口请填写。','密码列请使用文本格式，避免丢失前导零。提供的密码验证成功后自动保存到系统凭据管理器，可在机器的 SSH 密码设置中删除。','一次最多 100 台；文件内重复行跳过。按 SSH 别名或实际地址、账号、端口匹配已有机器；只补存密码，不重复添加、不更改密钥或跳板。匹配多台时请改填唯一 SSH 别名。','勾选后台配置免密后，先完成导入，再单独排队追加并验证公钥；已有机器仅补存密码，不执行此操作。']:
        notes.append([text]);notes.cell(notes.max_row,1).font=Font(name='Arial',size=11)
    notes.column_dimensions['A'].width=105
    output=io.BytesIO();book.save(output);book.close();return output.getvalue()


def safe_failure(error,*,key=False):
    if isinstance(error,WorkbookError):return str(error)
    # Classify only. Never echo arbitrary server output or exception arguments.
    text=str(getattr(error,'detail',error)).lower()
    if 'host key' in text or 'fingerprint' in text or '指纹' in text:
        return '主机指纹未受信任或已变化，请先在终端核对指纹并信任后重试'
    if isinstance(error,TimeoutError) or any(word in text for word in ('timed out','timeout','超时')):
        return '连接或验证超时，请检查网络、SSH 端口和服务器响应'
    if any(word in text for word in ('permission denied','authentication','password','密码')) and not key:
        return '账号或密码错误，或服务器拒绝此登录方式'
    if any(word in text for word in ('refused','actively refused','拒绝连接')):
        return '连接被拒绝，请检查 SSH 端口和服务器 SSH 服务'
    if any(word in text for word in ('resolve','getaddrinfo','name or service','no such host')):
        return '无法解析主机地址，请检查 IP / 主机名'
    if key:return '免密配置或独立验证失败，请检查远端 .ssh 写入权限及公钥认证设置'
    return '连接失败，请检查网络、SSH 端口、账号和认证配置'
