# Deterministic, dependency-free rendering of backend/assets/workbench.svg.
# Keep the editable SVG and these GDI+ primitives in sync when changing the mark.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$assetRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\assets'

function Rounded-Path([single]$x,[single]$y,[single]$width,[single]$height,[single]$radius) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $radius * 2
    $p.AddArc($x,$y,$d,$d,180,90)
    $p.AddArc(($x+$width-$d),$y,$d,$d,270,90)
    $p.AddArc(($x+$width-$d),($y+$height-$d),$d,$d,0,90)
    $p.AddArc($x,($y+$height-$d),$d,$d,90,90)
    $p.CloseFigure()
    return ,$p
}

function Render-Icon([int]$size) {
    $large = New-Object System.Drawing.Bitmap ($size*4),($size*4)
    $g = [Drawing.Graphics]::FromImage($large)
    $g.Clear([Drawing.Color]::Transparent)
    $g.SmoothingMode = 'AntiAlias'
    $g.ScaleTransform(($size/8.0),($size/8.0))
    $navy = New-Object Drawing.SolidBrush ([Drawing.ColorTranslator]::FromHtml('#152c39'))
    $mint = New-Object Drawing.SolidBrush ([Drawing.ColorTranslator]::FromHtml('#70e2c3'))
    $white = New-Object Drawing.Pen ([Drawing.ColorTranslator]::FromHtml('#e9fff9')),2
    $edge = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(140,112,216,193)),1
    $white.StartCap = 'Round'; $white.EndCap = 'Round'
    $tile = Rounded-Path 1 1 30 30 8
    $chip = Rounded-Path 8 8 16 16 3
    $core = Rounded-Path 12 12 8 8 1.5
    try {
        $g.FillPath($navy,$tile); $g.DrawPath($edge,$tile)
        $g.DrawPath($white,$chip)
        foreach ($pin in @(@(12,5,12,8),@(20,5,20,8),@(5,12,8,12),@(5,20,8,20),@(24,12,27,12),@(24,20,27,20),@(12,24,12,27),@(20,24,20,27))) {
            $g.DrawLine($white,[single]$pin[0],[single]$pin[1],[single]$pin[2],[single]$pin[3])
        }
        $g.FillPath($mint,$core)
        $g.FillEllipse($navy,20,20,10,10)
        $g.FillEllipse($mint,[single]21.5,[single]21.5,7,7)
        $small = New-Object Drawing.Bitmap $size,$size
        $scaled = [Drawing.Graphics]::FromImage($small)
        try {
            $scaled.InterpolationMode='HighQualityBicubic'
            $scaled.CompositingQuality='HighQuality'
            $scaled.PixelOffsetMode='HighQuality'
            $scaled.DrawImage($large,0,0,$size,$size)
        } finally { $scaled.Dispose() }
        return ,$small
    } finally {
        $g.Dispose(); $large.Dispose(); $navy.Dispose(); $mint.Dispose(); $white.Dispose(); $edge.Dispose()
        $tile.Dispose(); $chip.Dispose(); $core.Dispose()
    }
}

$sizes = @(16,20,24,32,40,48,64,128,256)
$frames = @()
foreach ($size in $sizes) {
    $bitmap = Render-Icon $size
    $stream = New-Object IO.MemoryStream
    try {
        $bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
        $frames += ,$stream.ToArray()
        if ($size -eq 128) { $bitmap.Save((Join-Path $assetRoot 'workbench.png'),[Drawing.Imaging.ImageFormat]::Png) }
    } finally { $stream.Dispose(); $bitmap.Dispose() }
}
$output = [IO.File]::Create((Join-Path $assetRoot 'workbench.ico'))
$writer = New-Object IO.BinaryWriter $output
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$sizes.Count)
    $offset = 6 + 16 * $sizes.Count
    for ($i=0; $i -lt $sizes.Count; $i++) {
        $dimension = if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
        $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$frames[$i].Length); $writer.Write([uint32]$offset)
        $offset += $frames[$i].Length
    }
    foreach ($frame in $frames) { $writer.Write([byte[]]$frame) }
} finally { $writer.Dispose() }
Write-Output 'Created workbench.ico (16-256 px) and workbench.png.'
