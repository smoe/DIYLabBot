# Offline XSD validation of the C01 interface; does not run a device server.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskErrors = [System.Collections.Generic.List[string]]::new()
$taskSettings = [System.Xml.XmlReaderSettings]::new()
$taskSettings.ValidationType = [System.Xml.ValidationType]::Schema
$taskSettings.Schemas.XmlResolver = [System.Xml.XmlUrlResolver]::new()
[void]$taskSettings.Schemas.Add('http://www.sila-standard.org', (Join-Path $taskRoot 'exports/research/sila2-schema/FeatureDefinition.xsd'))
$taskSettings.add_ValidationEventHandler({ param($taskSender, $taskEvent) $taskErrors.Add($taskEvent.Message) })
$taskReader = [System.Xml.XmlReader]::Create((Join-Path $taskRoot 'interfaces/tube-station-c01/TubeStationControl-v1_0.sila.xml'), $taskSettings)
try { while ($taskReader.Read()) {} } finally { $taskReader.Close() }
if ($taskErrors.Count -gt 0) { throw ($taskErrors -join [Environment]::NewLine) }
Write-Output 'Official SiLA XSD validation passed; server conformance is not tested.'
