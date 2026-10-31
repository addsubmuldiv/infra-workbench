import os
from pathlib import Path

import pytest
from backend import files_search as search


def test_current_directory_and_recursive_literal_name_search(tmp_path):
    (tmp_path/'sub').mkdir();(tmp_path/'MODEL.py').write_text('x');(tmp_path/'sub'/'model.txt').write_text('y')
    (tmp_path/'file[1].txt').write_text('literal')
    result=search.search(str(tmp_path),'model')
    assert [entry['name'] for entry in result['entries']]==['MODEL.py']
    result=search.search(str(tmp_path),'model',recursive=True,realtime=True)
    assert {entry['relative'] for entry in result['entries']}=={'MODEL.py',str(Path('sub/model.txt'))}
    assert search.search(str(tmp_path),'[1]')['entries'][0]['name']=='file[1].txt'


def test_locate_is_preferred_and_no_index_match_falls_back(tmp_path,monkeypatch):
    (tmp_path/'fresh.txt').write_text('new')
    monkeypatch.setattr(search.shutil,'which',lambda name:'/usr/bin/locate' if name=='locate' else None)
    real=search.indexed_paths;calls=[]
    def indexed(args,root,query,recursive):
        calls.append(args)
        return dict(path=root,parent=str(tmp_path.parent),entries=[],total=0,next_offset=None,scanned=0,truncated=False,skipped=0)
    monkeypatch.setattr(search,'indexed_paths',indexed)
    result=search.search(str(tmp_path),'fresh')
    assert calls[0][:5]==['/usr/bin/locate','-0','-i','-l','2000']
    assert result['entries'][0]['name']=='fresh.txt' and not result['indexed']
    assert result['locate_available'] is True  # An index miss must not suggest reinstalling.
    calls.clear();result=search.search(str(tmp_path),'fresh',realtime=True);assert calls==[]
    assert result['locate_available'] is True
    def hit(args,root,query,recursive):
        value=indexed(args,root,query,recursive);value['entries']=[dict(name='fresh.txt',path=str(tmp_path/'fresh.txt'))];value['total']=1;return value
    monkeypatch.setattr(search,'indexed_paths',hit)
    result=search.search(str(tmp_path),'fresh');assert result['engine']=='locate' and result['indexed']
    assert result['locate_available'] is True


def test_missing_locate_is_reported_and_rechecked_after_install(tmp_path,monkeypatch):
    (tmp_path/'fresh.txt').write_text('new')
    monkeypatch.setattr(search.shutil,'which',lambda _:None)
    result=search.search(str(tmp_path),'fresh')
    assert result['locate_available'] is False and result['entries'][0]['name']=='fresh.txt'
    monkeypatch.setattr(search.shutil,'which',lambda name:'/usr/bin/plocate' if name=='plocate' else None)
    monkeypatch.setattr(search,'indexed_paths',lambda *args:result)
    result=search.search(str(tmp_path),'fresh')
    assert result['locate_available'] is True and result['engine']=='plocate'


def test_search_limits_results_and_never_descends_directory_links(tmp_path,monkeypatch):
    for index in range(205): (tmp_path/f'match-{index}').write_text('')
    monkeypatch.setattr(search.shutil,'which',lambda _:None)
    result=search.search(str(tmp_path),'match',recursive=True)
    assert result['truncated'] and len(result['entries'])==200
    for value in ('','\n','a'*101):
        if value=='\n': continue  # A newline can be a literal filename search term.
        with pytest.raises(ValueError): search.search(str(tmp_path),value)
