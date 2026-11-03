"""Two approved floating layouts: machine counts or the original side-by-side cards."""
from math import ceil
MIN_SIZE = (220, 190)
DEFAULT_SIZE = (315, 260)
DRAW_SCALE = .65
MAX_SIZE = (520, 480)


def resolution_scale(width, height):
    """Use physical monitor pixels, including portrait displays, not work area."""
    short, long = sorted((width, height))
    return 1.25 if short >= 2160 and long >= 3840 else 1.


def clamp_size(width, height):
    return max(MIN_SIZE[0], min(MAX_SIZE[0], int(width))), max(MIN_SIZE[1], min(MAX_SIZE[1], int(height)))


def viewport_layout(width, height, host_count=None):
    width, height = clamp_size(width, height)
    count=max(1,host_count) if host_count is not None else 3
    if host_count is not None:
        content_limit=(max(MIN_SIZE[1],ceil((84+40*count)*DRAW_SCALE)) if width<300
                       else max(DEFAULT_SIZE[1],ceil((154+82*count)*DRAW_SCALE)))
        height=min(height,content_limit)
    design_width,design_height=width/DRAW_SCALE,height/DRAW_SCALE
    target_rows=min(3,count)
    rows_without_summary=max(0,int((design_height-61-49+6)/82))
    minimal=width<300 or rows_without_summary<target_rows
    rows_with_summary=max(0,int((design_height-111-49+6)/82))
    show_summary=not minimal and rows_with_summary>=target_rows
    content_top=52 if minimal else 111 if show_summary else 61
    row_height=40 if minimal else 76
    page_size=max(1,int((design_height-84)/40)) if minimal else (rows_with_summary if show_summary else rows_without_summary)
    columns=max(1,int((design_width-30)/112))
    device_rows=max(1,int((design_height-183)/74))
    return dict(width=width,height=height,minimal=minimal,show_summary=show_summary,page_size=page_size,
                row_height=row_height,content_top=content_top,detail_columns=columns,
                detail_page_size=columns*device_rows,scale=DRAW_SCALE)
