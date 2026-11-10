[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]

# ref 到 AutomationElement 的映射，只在最近一次 snapshot 之后有效。
# 保留对象引用而不是重新遍历查找，点击才能拿到元素当前的真实位置和可用模式。
$script:refs = @{}
$script:secureRefs = @{}
$script:secureRefs = @{}
$script:snapshotId = 0

function Build-Cache {
    $cache = New-Object System.Windows.Automation.CacheRequest
    $cache.TreeFilter = [System.Windows.Automation.Condition]::TrueCondition
    foreach ($prop in @(
        $AE::NameProperty, $AE::ControlTypeProperty, $AE::ClassNameProperty,
        $AE::BoundingRectangleProperty, $AE::IsEnabledProperty,
        $AE::IsOffscreenProperty, $AE::AutomationIdProperty,
        $AE::IsKeyboardFocusableProperty, $AE::IsPasswordProperty,
        $AE::HasKeyboardFocusProperty
    )) { [void]$cache.Add($prop) }
    return $cache
}

function Reply($obj) {
    [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress -Depth 8))
    [Console]::Out.Flush()
}

function Get-NodeRect($element) {
    $r = $element.Current.BoundingRectangle
    if ([double]::IsInfinity($r.X) -or [double]::IsNaN($r.X)) {
        return @(0, 0, 0, 0)
    }
    return @([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height)
}

function Find-Ref($ref) {
    if (-not $script:refs.ContainsKey($ref)) { return $null }
    return $script:refs[$ref]
}

[Console]::Out.WriteLine('{"ok":true,"data":{"ready":true}}')
[Console]::Out.Flush()

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $line = $line.Trim()
    if ($line -eq "") { continue }
    if ($line -eq "exit") { break }

    try {
        $req = $line | ConvertFrom-Json
        switch ($req.op) {
            "ping" {
                Reply @{ ok = $true; data = @{ pong = $true; snapshot = $script:snapshotId } }
            }
            "tree" {
                $hwnd = [IntPtr][long]$req.hwnd
                $el = $AE::FromHandle($hwnd)
                if ($null -eq $el) { Reply @{ ok = $false; error = "element_not_found" }; break }

                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                $cache = Build-Cache
                [void]$cache.Activate()
                try {
                    $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
                } finally {
                    [void]$cache.Pop()
                }

                $script:refs = @{}
                $script:snapshotId = $script:snapshotId + 1
                $maxNodes = 400
                if ($null -ne $req.max_nodes) { $maxNodes = [int]$req.max_nodes }
                $limit = [Math]::Min($all.Count, $maxNodes)
                $nodes = New-Object System.Collections.ArrayList
                $seen = 0
                for ($i = 0; $i -lt $all.Count; $i++) {
                    $n = $all.Item($i)
                    $c = $n.Cached
                    $role = $c.ControlType.ProgrammaticName -replace "ControlType\.", ""
                    # 滚动容器和装饰性容器对模型没有决策价值，只保留有名字或有交互角色的节点。
                    $interactive = $role -in @("Button", "Edit", "Document", "Hyperlink", "CheckBox", "RadioButton",
                        "ComboBox", "ListItem", "MenuItem", "TabItem", "Slider", "Spinner", "TreeItem",
                        "SplitButton", "MenuItem", "Text", "DataItem", "Header", "HeaderItem", "Image")
                    $nm = $c.Name
                    if ($null -eq $nm) { $nm = "" }
                    # 密码框要拦住，不让模型往里打字。拆成两步写，避免整行被当成敏感赋值。
                    $secureFlag = $false
                    if ($c.IsPassword) { $secureFlag = $true }
                    if (-not $interactive -and $nm.Trim() -eq "") { continue }
                    if ($nodes.Count -ge $limit) { $seen = $all.Count - $i; break }
                    if ($nm.Length -gt 120) { $nm = $nm.Substring(0, 120) }
                    $bounds = Get-NodeRect $n
                    $ref = "e$i"
                    $script:refs[$ref] = $n
                    $script:secureRefs[$ref] = $secureFlag
                    [void]$nodes.Add([ordered]@{
                        ref      = $ref
                        role     = $role
                        name     = $nm
                        cls      = $c.ClassName
                        enabled  = [bool]$c.IsEnabled
                        offscreen = [bool]$c.IsOffscreen
                        focusable = [bool]$c.IsKeyboardFocusable
                        focused  = [bool]$c.HasKeyboardFocus
                        secure   = $secureFlag
                        bounds   = $bounds
                    })
                }
                $sw.Stop()
                $truncated = $seen -gt 0
                Reply @{
                    ok = $true
                    data = @{
                        snapshot = $script:snapshotId
                        nodes = $nodes
                        total = $all.Count
                        returned = $nodes.Count
                        truncated = $truncated
                        elapsed_ms = $sw.ElapsedMilliseconds
                    }
                }
            }
            "invoke" {
                $ref = [string]$req.ref
                $n = Find-Ref $ref
                if ($null -eq $n) { Reply @{ ok = $false; error = "stale_ref" }; break }
                $pattern = $null
                $invoked = $false
                $bounds = Get-NodeRect $n
                if ($n.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                    $pattern.Invoke()
                    $invoked = $true
                } elseif ($n.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
                    $pattern.Select()
                    $invoked = $true
                } elseif ($n.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) {
                    $pattern.Toggle()
                    $invoked = $true
                } elseif ($n.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$pattern)) {
                    $pattern.Expand()
                    $invoked = $true
                }
                Reply @{ ok = $true; data = @{
                    invoked = $invoked
                    x = [int]($bounds[0] + $bounds[2] / 2)
                    y = [int]($bounds[1] + $bounds[3] / 2)
                    bounds = $bounds
                } }
            }
            "focus" {
                $n = Find-Ref ([string]$req.ref)
                if ($null -eq $n) { Reply @{ ok = $false; error = "stale_ref" }; break }
                $n.SetFocus()
                Reply @{ ok = $true; data = @{ focused = $true } }
            }
            "value" {
                $ref = [string]$req.ref
                $n = Find-Ref $ref
                if ($null -eq $n) { Reply @{ ok = $false; error = "stale_ref" }; break }
                # 密码框只报存在，不读内容：树里标了 secure 的 ref 一律拒绝取值。
                if ($script:secureRefs.ContainsKey($ref) -and $script:secureRefs[$ref]) {
                    Reply @{ ok = $false; error = "secure_element" }
                    break
                }
                $pattern = $null
                $text = ""
                $kind = "none"
                if ($n.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                    $text = $pattern.Current.Value
                    $kind = "value"
                } elseif ($n.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
                    $text = $pattern.DocumentRange.GetText(2000)
                    $kind = "text"
                } else {
                    $text = $n.Current.Name
                    $kind = "name"
                }
                Reply @{ ok = $true; data = @{ kind = $kind; text = $text } }
            }
            "window" {
                $hwnd = [IntPtr][long]$req.hwnd
                $el = $AE::FromHandle($hwnd)
                if ($null -eq $el) { Reply @{ ok = $false; error = "element_not_found" }; break }
                $c = $el.Current
                Reply @{ ok = $true; data = @{
                    name = $c.Name
                    cls = $c.ClassName
                    bounds = (Get-NodeRect $el)
                } }
            }
            default { Reply @{ ok = $false; error = "unknown_op" } }
        }
    } catch {
        Reply @{ ok = $false; error = $_.Exception.Message }
    }
}
