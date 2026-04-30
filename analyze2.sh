echo '=== all unique TCP connections (by SYN) ==='
sudo tcpdump -nn -r /tmp/wedge.pcap 2>/dev/null | grep 'Flags \[S\]' | awk '{print $3, "->", $5}' | sort -u
echo ''
echo '=== all unique source IPs ==='
sudo tcpdump -nn -r /tmp/wedge.pcap 2>/dev/null | awk '{print $3}' | cut -d. -f1-4 | sort -u
echo ''
echo '=== full conversation timeline (deduplicated, In only) ==='
sudo tcpdump -nn -tttt -r /tmp/wedge.pcap 2>/dev/null | grep -E '^\d.*In ' | awk '{print $1, $2, $5, "->", $7, $NF}'
echo ''
echo '=== complete pcap, just In direction (chip responses) ==='
sudo tcpdump -nn -tttt -r /tmp/wedge.pcap 2>/dev/null | grep ' In '
