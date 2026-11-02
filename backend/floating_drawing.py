"""Small cached, supersampled round-rectangle textures; text stays native Tk text."""
from functools import lru_cache
from PIL import Image, ImageDraw

@lru_cache(maxsize=256)
def rounded_sprite(width,height,radius,fill,outline,background):
    width,height=max(1,width),max(1,height)
    scale=4
    image=Image.new('RGB',(width*scale,height*scale),background)
    drawing=ImageDraw.Draw(image)
    drawing.rounded_rectangle((0,0,width*scale-1,height*scale-1),radius=radius*scale,
                              fill=fill,outline=outline or fill,width=scale)
    return image.resize((width,height),Image.Resampling.LANCZOS)

@lru_cache(maxsize=64)
def pin_sprite(size,color,pinned):
    """A recognizable pushpin independent of installed symbol fonts."""
    scale=4
    image=Image.new('RGBA',(size*scale,size*scale))
    drawing=ImageDraw.Draw(image)
    unit=size*scale/24
    points=[(8,4),(16,4),(16,7),(14,8),(14,13),(18,16),(6,16),(10,13),(10,8),(8,7)]
    points=[(round(x*unit),round(y*unit)) for x,y in points]
    drawing.polygon(points,fill=color if pinned else None,outline=color,width=max(1,round(1.5*unit)))
    drawing.line([(12*unit,16*unit),(12*unit,22*unit)],fill=color,width=max(1,round(1.6*unit)))
    image=image.rotate(-30,resample=Image.Resampling.BICUBIC)
    return image.resize((size,size),Image.Resampling.LANCZOS)
