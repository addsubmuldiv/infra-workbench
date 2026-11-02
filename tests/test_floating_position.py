from backend.floating_position import dialog_position


def test_dialog_opens_on_the_right_when_it_fits():
    assert dialog_position((100,100,400,360),(350,330),(0,0,1920,1040))==(412,100)


def test_right_edge_dialog_opens_to_left_and_stays_above_taskbar():
    assert dialog_position((1600,800,1900,1000),(350,420),(0,0,1920,1040))==(1238,620)


def test_placement_uses_the_owners_monitor_and_handles_negative_coordinates():
    assert dialog_position((-400,80,-100,340),(350,330),(-1920,0,0,1040))==(-762,80)
    assert dialog_position((2500,50,2800,300),(350,330),(1920,0,3840,1040))==(2812,50)


def test_dialog_is_clamped_when_neither_side_fits():
    x,y=dialog_position((180,220,480,400),(500,420),(0,0,640,480))
    assert 0<=x<=140 and 0<=y<=60
