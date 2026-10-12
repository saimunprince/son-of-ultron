$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$scr = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$want = ([string]$env:SYRAX_SIGHT_TEXT).ToLowerInvariant()
$hits = New-Object System.Collections.ArrayList
if ($env:SYRAX_SIGHT_MODE -eq "ocr") {
  Add-Type -AssemblyName System.Drawing
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
  }
  $png = Join-Path $env:TEMP ("syrax-sight-" + [guid]::NewGuid().ToString("N") + ".png")
  $bmp = New-Object System.Drawing.Bitmap $scr.Width, $scr.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($scr.Location, [System.Drawing.Point]::Empty, $scr.Size)
  $g.Dispose()
  $bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($png)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $stream.Dispose()
    $n = 0
    foreach ($line in $result.Lines) {
      $n++
      foreach ($w in $line.Words) {
        $b = $w.BoundingRect
        [void]$hits.Add([pscustomobject]@{ text = [string]$w.Text; line = $n; x = [int]$b.X; y = [int]$b.Y; w = [int]$b.Width; h = [int]$b.Height })
      }
    }
  } finally {
    Remove-Item -LiteralPath $png -ErrorAction SilentlyContinue
  }
} else {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $A = [System.Windows.Automation.AutomationElement]
  $cond = New-Object System.Windows.Automation.PropertyCondition($A::IsOffscreenProperty, $false)
  function Scan($root, [bool]$fg) {
    foreach ($e in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)) {
      try {
        $c = $e.Current
        $name = [string]$c.Name
        $l = $name.ToLowerInvariant()
        if ($l.Length -eq 0 -or $l.Length -gt 200 -or -not ($l.Contains($want) -or ($l.Length -ge 3 -and $want.Contains($l)))) { continue }
        $r = $c.BoundingRectangle
        if ($r.Width -le 0 -or $r.Height -le 0 -or -not $c.IsEnabled) { continue }
        [void]$hits.Add([pscustomobject]@{ name = $name; type = ($c.ControlType.ProgrammaticName -replace '^ControlType\.', '');
            x = [int]($r.X + $r.Width / 2); y = [int]($r.Y + $r.Height / 2); w = [int]$r.Width; h = [int]$r.Height; fg = $fg })
      } catch { }
    }
  }
  $hwnd = [int64]$env:SYRAX_SIGHT_HWND
  if ($hwnd -ne 0) {
    try { Scan ($A::FromHandle([IntPtr]$hwnd)) $true } catch { }
  }
  if ($hits.Count -eq 0) { Scan $A::RootElement $false }
}
[pscustomobject]@{ screen = @($scr.Width, $scr.Height); hits = $hits.ToArray() } | ConvertTo-Json -Depth 4 -Compress
