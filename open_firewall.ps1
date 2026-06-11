# Run elevated - opens port 8000 and sets static IP 192.168.1.100
$rule = Get-NetFirewallRule -DisplayName "OxyPC Inventory API" -ErrorAction SilentlyContinue
if ($rule) { Remove-NetFirewallRule -DisplayName "OxyPC Inventory API" }
New-NetFirewallRule -DisplayName "OxyPC Inventory API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
Write-Host "Firewall port 8000 opened"

$current = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.1.*" -and $_.IPAddress -ne "192.168.1.100" } | Select-Object -First 1
if ($current) {
    $iface = $current.InterfaceAlias
    Remove-NetIPAddress -InterfaceAlias $iface -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $iface -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias $iface -IPAddress "192.168.1.100" -PrefixLength 24 -DefaultGateway "192.168.1.1"
    Set-DnsClientServerAddress -InterfaceAlias $iface -ServerAddresses ("8.8.8.8","8.8.4.4")
    Write-Host "Static IP 192.168.1.100 set on $iface"
}
Read-Host "Done. Press Enter to close"
