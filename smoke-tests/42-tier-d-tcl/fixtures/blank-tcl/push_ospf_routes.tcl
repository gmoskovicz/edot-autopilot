#!/usr/bin/env tclsh
# ================================================================
# FILE:        push_ospf_routes.tcl
# DESCRIPTION: Network device configuration management
#              SSH to routers/switches via Expect, push OSPF route
#              changes, verify BGP peering, collect interface stats.
#
# RUNTIME:     Tcl 8.6 + Expect 5.45
# PLATFORM:    Network NOC server (Linux)
# SCHEDULE:    On-demand via change management system (ServiceNow)
# ================================================================

package require Expect

# ---- Configuration ------------------------------------------
set TIMEOUT      30
set SSH_USER     "netops"
set SSH_KEY      "/home/netops/.ssh/id_ed25519"
set LOG_DIR      "/var/log/netops/ospf_push"
set ROUTE_FILE   "route_changes.txt"

# ---- Route changes to push ----------------------------------
set ROUTE_CHANGES {
    {192.168.100.0/24  10.0.0.254  add}
    {172.16.50.0/22    10.0.0.252  modify}
    {10.50.0.0/16      null         withdraw}
}

# ---- Target devices -----------------------------------------
set DEVICES {
    {core-rtr-01.dc1   10.0.0.1   cisco_ios    core}
    {edge-rtr-03.dc1   10.0.0.3   cisco_ios_xr edge}
    {dist-sw-07.dc2    10.1.0.7   juniper_junos dist}
    {access-sw-22.dc2  10.1.1.22  cisco_nxos   access}
}

# ================================================================
# proc log_message — write timestamped log entry
# ================================================================
proc log_message {level msg} {
    set ts [clock format [clock seconds] -format "%Y-%m-%dT%H:%M:%S"]
    puts stderr "\[$ts\] \[$level\] $msg"
}

# ================================================================
# proc ssh_to_device — spawn SSH session to device
# ================================================================
proc ssh_to_device {hostname ip} {
    global SSH_USER SSH_KEY TIMEOUT

    log_message "INFO" "Connecting to $hostname ($ip) via SSH"
    spawn ssh -i $SSH_KEY -o StrictHostKeyChecking=no \
              -o ConnectTimeout=15 \
              ${SSH_USER}@${ip}

    set spawn_id_val $spawn_id

    expect {
        -timeout $TIMEOUT
        "#"        { log_message "INFO" "SSH session established: $hostname" }
        "$ "       { log_message "INFO" "SSH session established (shell): $hostname" }
        "assword:" {
            log_message "ERROR" "Password auth requested but key expected: $hostname"
            return -1
        }
        timeout    {
            log_message "ERROR" "SSH connection timed out: $hostname"
            return -1
        }
    }
    return $spawn_id_val
}

# ================================================================
# proc enter_config_mode — enter privileged config mode
# ================================================================
proc enter_config_mode {platform} {
    global TIMEOUT
    if {$platform eq "cisco_ios" || $platform eq "cisco_ios_xr" || \
        $platform eq "cisco_nxos"} {
        send "enable\r"
        expect -timeout $TIMEOUT "#"
        send "configure terminal\r"
        expect -timeout $TIMEOUT "(config)#"
    } elseif {$platform eq "juniper_junos"} {
        send "configure\r"
        expect -timeout $TIMEOUT "(edit)"
    }
}

# ================================================================
# proc push_route_change — push one OSPF route change
# ================================================================
proc push_route_change {platform prefix next_hop action} {
    global TIMEOUT
    if {$platform eq "cisco_ios" || $platform eq "cisco_ios_xr"} {
        if {$action eq "withdraw"} {
            send "no ip route $prefix\r"
        } elseif {$action eq "add" || $action eq "modify"} {
            send "ip route $prefix $next_hop\r"
        }
    } elseif {$platform eq "juniper_junos"} {
        set dest [lindex [split $prefix /] 0]
        set masklen [lindex [split $prefix /] 1]
        if {$action eq "withdraw"} {
            send "delete routing-options static route $prefix\r"
        } else {
            send "set routing-options static route $prefix next-hop $next_hop\r"
        }
    }
    expect -timeout $TIMEOUT -re {#|\(edit\)}
}

# ================================================================
# proc verify_bgp — verify BGP peer state
# ================================================================
proc verify_bgp {hostname platform} {
    global TIMEOUT
    if {$platform eq "cisco_ios"} {
        send "show bgp summary\r"
    } elseif {$platform eq "cisco_ios_xr"} {
        send "show bgp all summary\r"
    } elseif {$platform eq "juniper_junos"} {
        send "run show bgp summary\r"
    } elseif {$platform eq "cisco_nxos"} {
        send "show bgp all summary\r"
    }
    expect -timeout $TIMEOUT -re {#|\(edit\)}
    log_message "INFO" "BGP summary retrieved from $hostname"
}

# ================================================================
# proc collect_interface_stats — collect interface counters
# ================================================================
proc collect_interface_stats {hostname platform} {
    global TIMEOUT
    if {$platform eq "cisco_ios" || $platform eq "cisco_ios_xr" || \
        $platform eq "cisco_nxos"} {
        send "show interface counters\r"
    } elseif {$platform eq "juniper_junos"} {
        send "run show interfaces statistics brief\r"
    }
    expect -timeout $TIMEOUT -re {#|\(edit\)}
    log_message "INFO" "Interface stats collected from $hostname"
}

# ================================================================
# proc configure_device — full config push for one device
# ================================================================
proc configure_device {device} {
    global ROUTE_CHANGES
    lassign $device hostname ip platform role

    log_message "INFO" "=== Configuring $hostname ($platform / $role) ==="

    # SSH connect
    set sid [ssh_to_device $hostname $ip]
    if {$sid == -1} {
        log_message "ERROR" "Skipping $hostname — connection failed"
        return 1
    }

    # Enter config mode
    enter_config_mode $platform

    # Push each route change
    set error_count 0
    foreach route $ROUTE_CHANGES {
        lassign $route prefix next_hop action
        if {[catch {push_route_change $platform $prefix $next_hop $action} err]} {
            log_message "ERROR" "Route push failed on $hostname: $err"
            incr error_count
        } else {
            log_message "INFO" "Route $action $prefix on $hostname — OK"
        }
    }

    # Commit (Junos) or end (IOS)
    if {$platform eq "juniper_junos"} {
        send "commit confirmed 5\r"
        expect -timeout 30 "(edit)"
        send "commit\r"
        expect -timeout 30 "(edit)"
    } else {
        send "end\r"
        expect -timeout 15 "#"
        send "write memory\r"
        expect -timeout 30 "#"
    }

    # Verify BGP after change
    verify_bgp $hostname $platform

    # Collect interface stats
    collect_interface_stats $hostname $platform

    # Disconnect
    send "exit\r"
    expect eof

    log_message "INFO" "=== Done: $hostname — errors=$error_count ==="
    return $error_count
}

# ================================================================
# MAIN
# ================================================================
file mkdir $LOG_DIR

set total_errors 0
set devices_done 0

foreach device $DEVICES {
    set errs [configure_device $device]
    incr total_errors $errs
    incr devices_done
}

puts "\n=== Network Change Push Summary ==="
puts "Devices configured: $devices_done"
puts "Route changes:      [llength $ROUTE_CHANGES]"
puts "Errors:             $total_errors"

if {$total_errors > 0} {
    exit 1
}
exit 0
