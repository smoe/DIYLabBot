# Offline official-schema validation; not a SiLA server interoperability test.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskErrors = [System.Collections.Generic.List[string]]::new()
$taskSettings = [System.Xml.XmlReaderSettings]::new()
$taskSettings.ValidationType = [System.Xml.ValidationType]::Schema
$taskSettings.Schemas.XmlResolver = [System.Xml.XmlUrlResolver]::new()
[void]$taskSettings.Schemas.Add('http://www.sila-standard.org', (Join-Path $taskRoot 'exports/research/sila2-schema/FeatureDefinition.xsd'))
$taskSettings.add_ValidationEventHandler({ param($taskSender, $taskEvent) $taskErrors.Add($taskEvent.Message) })
$taskReader = [System.Xml.XmlReader]::Create((Join-Path $taskRoot 'interfaces/centrifuge-cf01/CentrifugeControl-v1_0.sila.xml'), $taskSettings)
try { while ($taskReader.Read()) {} } finally { $taskReader.Close() }
if ($taskErrors.Count -gt 0) { throw ($taskErrors -join [Environment]::NewLine) }
Write-Output 'CF01 official SiLA XSD validation passed; no live server tested.'
