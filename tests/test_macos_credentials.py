
def test_sudo_credential_read_failure_is_unknown_not_missing(tmp_path):
    from backend.sudo import SudoService
    class Denied:
        supported=True
        def get(self,key):raise RuntimeError('SYNTHETIC-SECRET-MUST-NOT-LEAK')
    view=SudoService(None,Denied()).view(dict(id='synthetic'))
    assert view['password_saved'] is None
    assert '未删除' in view['credential_error']
    assert 'SYNTHETIC' not in str(view)
