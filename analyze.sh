echo '=== flag breakdown ==='
sudo tcpdump -nn -r /tmp/wedge.pcap 2>/dev/null | grep -oE 'Flags \[[^]]+\]' | sort | uniq -c | sort -rn
echo ''
echo '=== first 12 packets ==='
sudo tcpdump -nn -tttt -r /tmp/wedge.pcap 2>/dev/null | head -12
echo ''
echo '=== last 20 packets ==='
sudo tcpdump -nn -tttt -r /tmp/wedge.pcap 2>/dev/null | tail -20
echo ''
echo '=== unique source-flag combos around the wedge ==='
sudo tcpdump -nn -r /tmp/wedge.pcap 2>/dev/null | awk '{print $3,$5,$6,$7}' | sort | uniq -c | sort -rn | head -10
