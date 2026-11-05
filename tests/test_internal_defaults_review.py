"""Final-review regressions: public streaming gates and parser errors report actual policy."""
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_streaming_entry_errors_report_actual_limits(monkeypatch,tmp_path):
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    from backend import server_import_routes,skill_routes
    app=FastAPI()
    monkeypatch.setattr(server_import_routes,'MAX_FILE',8)
    monkeypatch.setattr(skill_routes,'UPLOAD_LIMIT',8)
    server_import_routes.register_import_routes(app,[],None,None)
    skill_routes.register_skill_routes(app,SimpleNamespace(),lambda:[])
    with TestClient(app) as client:
        for url,expected in [('/api/imports/preview','Excel 文件不能超过 8 B'),('/api/skills/import?filename=a.zip','导入文件不能超过 8 B')]:
            response=client.post(url,content=b'x'*9)
            assert response.status_code==413
            assert response.json()['detail']==expected


def test_log_parser_errors_report_actual_line_and_record_limits(monkeypatch):
    from backend import log_reader
    with monkeypatch.context() as patch:
        patch.setattr(log_reader,'MAX_LINE',4)
        with pytest.raises(ValueError,match='超过 4 B'):
            log_reader.parse_lines(['abcde'])
    rows=[json.dumps({'iteration':i,'loss':1}) for i in (1,2)]
    with pytest.raises(ValueError,match='超过 1 条'):
        log_reader.parse_lines(rows,max_records=1)
