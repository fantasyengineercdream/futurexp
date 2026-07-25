param(
  [string]$TowerUrl = "https://oocc-infinite-channel-demo.pages.dev/",
  [string]$RoomUrl = "https://oc-voice.open.smn.icu/"
)

$ErrorActionPreference = "Stop"

function Get-Utf8Text([string]$Url) {
  $response = Invoke-WebRequest -UseBasicParsing $Url
  if ($response.StatusCode -ne 200) {
    throw "GET $Url returned $($response.StatusCode)"
  }
  return [Text.Encoding]::UTF8.GetString(
    $response.RawContentStream.ToArray()
  )
}

function Assert-Contains(
  [string]$Text,
  [string]$Expected,
  [string]$Label
) {
  if (-not $Text.Contains($Expected)) {
    throw "$Label is missing: $Expected"
  }
}

function Assert-Excludes(
  [string]$Text,
  [string]$Unexpected,
  [string]$Label
) {
  if ($Text.Contains($Unexpected)) {
    throw "$Label unexpectedly contains: $Unexpected"
  }
}

$towerEntry = Get-Utf8Text $TowerUrl
Assert-Contains $towerEntry "integration-20" "Tower entry"
Assert-Contains $towerEntry 'id="coreLocator"' "Tower locator"

$towerApp = Get-Utf8Text ([Uri]::new(
  [Uri]$TowerUrl,
  "app.js?v=integration-20"
).AbsoluteUri)
Assert-Contains $towerApp "https://oc-voice.open.smn.icu/" "Tower app"
Assert-Excludes $towerApp "https://oc-voice-lab.pages.dev/" "Tower app"
Assert-Contains $towerApp "rotateY(180deg)" "Tower inward-facing geometry"
Assert-Contains $towerApp "applyScheduledResidentState" "Scheduler-driven resident"
Assert-Excludes $towerApp "startTransitRouteLoop" "Retired frontend route"
Assert-Contains $towerApp "showTransitBaseScreen" "Milk frog background preservation"
Assert-Contains $towerApp "const CORE_SHOWCASE_SPIN = 0.008" "Moving core showcase row"
$milkFrog =
  [string][char]0x5976 +
  [string][char]0x86D9
Assert-Contains $towerApp $milkFrog "Milk frog label"

$towerStyles = Get-Utf8Text ([Uri]::new(
  [Uri]$TowerUrl,
  "styles.css?v=integration-20"
).AbsoluteUri)
Assert-Contains $towerStyles "bottom: -18px" "Unobstructed resident labels"
Assert-Contains $towerStyles "scaleX(-1)" "Forward-facing milk frog"

$towerBridge = Get-Utf8Text ([Uri]::new(
  [Uri]$TowerUrl,
  "room-bridge.js?v=integration-20"
).AbsoluteUri)
Assert-Contains $towerBridge 'homeSlotId: "transit-01"' "Milk frog home"
Assert-Contains $towerBridge 'advancedBy !== "scheduler"' "Scheduler boundary"
Assert-Excludes $towerBridge "previewTransitStates" "Retired preview route"

$roomEntry = Get-Utf8Text $RoomUrl
$roomAssetMatch = [regex]::Match(
  $roomEntry,
  'src="([^"]+\.js)"'
)
if (-not $roomAssetMatch.Success) {
  throw "Room entry does not contain a JavaScript bundle"
}
$roomBundle = Get-Utf8Text ([Uri]::new(
  [Uri]$RoomUrl,
  $roomAssetMatch.Groups[1].Value
).AbsoluteUri)
$expectedExit =
  [string][char]0x2190 + " " +
  [string][char]0x8FD4 +
  [string][char]0x56DE +
  [string][char]0x65E0 +
  [string][char]0x9650 +
  [string][char]0x7535 +
  [string][char]0x89C6 +
  [string][char]0x5854
Assert-Contains $roomBundle "BUILD 2026.07.25.9" "Room bundle"
Assert-Contains $roomBundle $expectedExit "Room exit"
Assert-Excludes $roomBundle 'id="character-switch"' "Room identity boundary"
Assert-Excludes $roomBundle "Object.values(CHARACTERS)" "Room asset cache"

foreach ($roomImage in @(
  "rooms/angel-room-pixel-v1.webp",
  "rooms/devil-room-pixel-v1.webp"
)) {
  [void](Get-Utf8Text ([Uri]::new(
    [Uri]$RoomUrl,
    $roomImage
  ).AbsoluteUri))
}

$dayLoopUrl = [Uri]::new(
  [Uri]$TowerUrl,
  "api/living-world/day-loop-runs"
).AbsoluteUri
$dayLoopResponse = Invoke-WebRequest `
  -UseBasicParsing `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"seed":"production-smoke"}' `
  $dayLoopUrl
if ($dayLoopResponse.StatusCode -ne 201) {
  throw "Day Loop create returned $($dayLoopResponse.StatusCode)"
}
$dayLoop = [Text.Encoding]::UTF8.GetString(
  $dayLoopResponse.RawContentStream.ToArray()
) | ConvertFrom-Json
if (
  $dayLoop.schemaVersion -ne "0.1" -or
  -not $dayLoop.runId -or
  $dayLoop.dayIndex -ne 1 -or
  $dayLoop.timeline.Count -ne 5
) {
  throw "Day Loop production response does not match v0.1"
}
if (
  @($dayLoop.timeline | Where-Object {
    $_.advancedBy -ne "scheduler"
  }).Count -ne 0
) {
  throw "Day Loop production timeline is not scheduler-authored"
}

Write-Output "PRODUCTION_SMOKE=PASS"
Write-Output "TOWER=$TowerUrl"
Write-Output "ROOM=$RoomUrl"
Write-Output "RUN_ID=$($dayLoop.runId)"
