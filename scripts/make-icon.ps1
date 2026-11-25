# Deterministic, dependency-free rendering of backend/assets/workbench.svg.
# Keep the editable SVG and these GDI+ primitives in sync when changing the mark.
param(
    [string]$ExportPng1024 = ''
)
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

function Spark-Path() {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $p.AddBezier([single]32,[single]21, [single]32.9,[single]27.5, [single]36.5,[single]31.1, [single]43,[single]32)
    $p.AddBezier([single]43,[single]32, [single]36.5,[single]32.9, [single]32.9,[single]36.5, [single]32,[single]43)
    $p.AddBezier([single]32,[single]43, [single]31.1,[single]36.5, [single]27.5,[single]32.9, [single]21,[single]32)
    $p.AddBezier([single]21,[single]32, [single]27.5,[single]31.1, [single]31.1,[single]27.5, [single]32,[single]21)
    $p.CloseFigure()
    return ,$p
}

function Render-Icon([int]$size) {
    $supersample = if ($size -ge 512) { 2 } else { 4 }
    $canvas = $size * $supersample
    $large = New-Object System.Drawing.Bitmap $canvas,$canvas
    $g = [Drawing.Graphics]::FromImage($large)
    $g.Clear([Drawing.Color]::Transparent)
    $g.SmoothingMode = 'AntiAlias'
    $g.PixelOffsetMode = 'HighQuality'
    $g.ScaleTransform(($canvas / 64.0),($canvas / 64.0))

    $tile = Rounded-Path 2 2 60 60 15
    $chip = Rounded-Path 16 16 32 32 8.5
    $spark = Spark-Path
    $glowCircle = New-Object System.Drawing.Drawing2D.GraphicsPath
    $glowCircle.AddEllipse([single]10,[single]10,[single]44,[single]44)

    $bgBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
        [Drawing.PointF]::new(8,4), [Drawing.PointF]::new(56,60),
        [Drawing.ColorTranslator]::FromHtml('#142d3b'),
        [Drawing.ColorTranslator]::FromHtml('#08141d')
    )
    $rimBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
        [Drawing.PointF]::new(0,0), [Drawing.PointF]::new(64,64),
        [Drawing.Color]::FromArgb(122,142,243,215),
        [Drawing.Color]::FromArgb(61,53,156,136)
    )
    $rimPen = New-Object Drawing.Pen $rimBrush,([single]1.5)
    $glowBrush = New-Object System.Drawing.Drawing2D.PathGradientBrush $glowCircle
    $glowBrush.CenterColor = [Drawing.Color]::FromArgb(82,105,245,206)
    $glowBrush.SurroundColors = @([Drawing.Color]::FromArgb(0,105,245,206))

    $pinPen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(148,104,201,180)),([single]2.4)
    $pinPen.StartCap = 'Round'; $pinPen.EndCap = 'Round'

    $chipBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
        [Drawing.PointF]::new(16,15), [Drawing.PointF]::new(48,49),
        [Drawing.ColorTranslator]::FromHtml('#25495c'),
        [Drawing.ColorTranslator]::FromHtml('#112330')
    )
    $chipPen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(178,134,237,208)),([single]1.5)
    $sheenPen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(115,208,255,242)),([single]1.0)
    $sheenPen.StartCap = 'Round'; $sheenPen.EndCap = 'Round'

    $sparkBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
        [Drawing.PointF]::new(22,21), [Drawing.PointF]::new(42,43),
        [Drawing.ColorTranslator]::FromHtml('#cafff0'),
        [Drawing.ColorTranslator]::FromHtml('#28c79e')
    )

    try {
        $g.FillPath($bgBrush,$tile)
        $g.SetClip($tile)
        $g.FillPath($glowBrush,$glowCircle)
        $g.ResetClip()
        $g.DrawPath($rimPen,$tile)

        foreach ($pin in @(
            @(25,10,25,13.8), @(39,10,39,13.8),
            @(25,50.2,25,54), @(39,50.2,39,54),
            @(10,25,13.8,25), @(10,39,13.8,39),
            @(50.2,25,54,25), @(50.2,39,54,39)
        )) {
            $g.DrawLine($pinPen,[single]$pin[0],[single]$pin[1],[single]$pin[2],[single]$pin[3])
        }

        $g.FillPath($chipBrush,$chip)
        $g.DrawPath($chipPen,$chip)
        $g.DrawLine($sheenPen,[single]22,[single]17.5,[single]42,[single]17.5)
        $g.FillPath($sparkBrush,$spark)

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
        $g.Dispose(); $large.Dispose()
        $bgBrush.Dispose(); $rimBrush.Dispose(); $rimPen.Dispose()
        $glowBrush.Dispose(); $glowCircle.Dispose()
        $pinPen.Dispose(); $chipBrush.Dispose(); $chipPen.Dispose()
        $sheenPen.Dispose(); $sparkBrush.Dispose()
        $tile.Dispose(); $chip.Dispose(); $spark.Dispose()
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

if ($ExportPng1024) {
    $hiRes = Render-Icon 1024
    try {
        $hiRes.Save($ExportPng1024,[Drawing.Imaging.ImageFormat]::Png)
    } finally { $hiRes.Dispose() }
    Write-Output "Exported 1024px PNG to $ExportPng1024."
}
Write-Output 'Created workbench.ico (16-256 px) and workbench.png.'
