echo '=== ALL SYN packets with full source info ==='
sudo tcpdump -nn -tttt -r /tmp/wedge.pcap 2>/dev/null | grep -v ' P ' | grep 'Flags \[S\]'
