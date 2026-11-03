from backend.floating_layout import viewport_layout, clamp_size


def test_resolution_scale_preserves_2k_and_enlarges_4k_in_both_orientations():
    from backend.floating_layout import resolution_scale
    for size in [(1920,1080),(2560,1440),(1440,2560),(3440,1440)]:
        assert resolution_scale(*size) == 1.
    for size in [(3840,2160),(2160,3840),(4096,2160),(5120,2880)]:
        assert resolution_scale(*size) == 1.25


def test_minimum_is_a_multi_machine_count_list():
    layout = viewport_layout(100, 50)
    assert (layout['width'],layout['height']) == (220,190)
    assert layout['minimal'] and layout['page_size'] >= 3


def test_normal_and_detail_use_identical_fixed_scale():
    small,normal,large = [viewport_layout(*size) for size in [(220,190),(363,296),(500,400)]]
    assert small['scale'] == normal['scale'] == large['scale'] == .65
    assert not normal['minimal'] and not large['minimal']
    assert large['page_size'] > normal['page_size']
    assert large['detail_page_size'] > normal['detail_page_size']


def test_layout_does_not_depend_on_the_selected_machine():
    assert viewport_layout(315,260)['detail_page_size'] == 8
    assert clamp_size(363,296) == (363,296)


def test_saved_size_is_validated_without_losing_old_preferences(tmp_path):
    import json
    from backend.floating_monitor import MonitorSettings
    path=tmp_path/'float.json'
    path.write_text(json.dumps(dict(width=10,height=10000,opacity=.6,host='server')))
    settings=MonitorSettings(path)
    assert settings.values['width']==220 and settings.values['height']==480
    assert settings.values['opacity']==.6 and settings.values['host']=='server'
    settings.update(width=500,height=400)
    restored=MonitorSettings(path)
    assert (restored.values['width'],restored.values['height'])==(500,400)


def test_card_view_starts_soon_after_minimum_and_size_is_bounded():
    from backend.floating_layout import viewport_layout
    assert viewport_layout(220,190,3)['minimal']
    assert viewport_layout(250,190,3)['minimal']
    assert not viewport_layout(300,254,3)['minimal']
    sparse=viewport_layout(240,900,3)
    assert sparse['height']==190
    normal=viewport_layout(1200,900,3)
    assert normal['width']<=520 and normal['height']<=300


def test_increasing_three_machine_view_never_drops_to_one_or_two():
    from backend.floating_layout import viewport_layout
    layouts=[viewport_layout(w,h,3) for w,h in [(220,190),(266,213),(315,235),(315,260),(450,320)]]
    assert all(layout['page_size']>=3 for layout in layouts)
    assert layouts[0]['minimal'] and layouts[1]['minimal']
    assert not layouts[2]['minimal']
    assert not layouts[2]['show_summary']
    assert layouts[3]['show_summary']


def test_compact_default_still_shows_three_full_machine_cards():
    from backend.floating_layout import viewport_layout,DEFAULT_SIZE
    layout=viewport_layout(*DEFAULT_SIZE,host_count=3)
    assert DEFAULT_SIZE[0]<=320 and DEFAULT_SIZE[1]<=260
    assert not layout['minimal'] and layout['page_size']>=3


def test_old_window_size_is_reduced_once_and_keeps_machine_selection(tmp_path):
    import json
    from backend.floating_monitor import MonitorSettings
    path=tmp_path/'float.json'
    path.write_text(json.dumps({'width':363,'height':296,'favorites':['a'],'opacity':.7}))
    migrated=MonitorSettings(path)
    assert migrated.values['width']==315 and migrated.values['height']==260
    assert migrated.values['favorites']==['a'] and migrated.values['opacity']==.7
    migrated.update(width=migrated.values['width'],height=migrated.values['height'])
    assert MonitorSettings(path).values==migrated.values
