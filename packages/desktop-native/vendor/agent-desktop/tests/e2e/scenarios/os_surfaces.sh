os_volume() { osascript -e "output volume of (get volume settings)" 2>/dev/null; }
os_ref() { printf '%s' "$1" | python3 "$json_tool" tree "$2" ref 2>/dev/null; }

os_wait_volume() {
    local value=""
    for _ in $(seq 1 25); do
        value="$(os_volume)"
        case "$value" in
            ''|*[!0-9]*) ;;
            *) if [ "$value" -ge 45 ] && [ "$value" -le 55 ]; then printf '%s' "$value"; return 0; fi ;;
        esac
        sleep 0.2
    done
    printf '%s' "$value"
    return 1
}

os_panel_open=0
os_cc_ref=""

os_wait_panel() {
    local want="$1" seen
    for _ in $(seq 1 15); do
        seen=closed
        [ -n "$(os_ref "$("$bin" snapshot --app "Control Center" -i 2>/dev/null)" Sound)" ] && seen=open
        [ "$seen" = "$want" ] && return 0
        sleep 0.2
    done
    return 1
}

os_close_panel() {
    [ "$os_panel_open" = 1 ] || return 0
    os_panel_open=0
    os_wait_panel closed && return 0
    "$bin" click "$os_cc_ref" >/dev/null 2>&1
    os_wait_panel closed
}

os_restore_volume() {
    os_close_panel || badmsg "the Control Center panel stayed open after its item was clicked again"
    osascript -e "set volume output volume $volume_original" >/dev/null 2>&1
}

os_control_center_volume() {
    local extras panel sound_ref detail slider_ref set_output volume volume_moved=0
    extras="$("$bin" snapshot --surface menu-bar-extras -i 2>/dev/null)"
    os_cc_ref="$(os_ref "$extras" "Control Center")"
    if [ -z "$os_cc_ref" ]; then
        badmsg "menu-bar-extras snapshot lists no Control Center item ref  [ok=$(json_field "$extras" ok)]"
        return
    fi
    okmsg "menu-bar-extras snapshot lists the Control Center item  [$os_cc_ref]"
    os_panel_open=1
    panel="$("$bin" click "$os_cc_ref" --wait-for "button:Sound" 2>/dev/null)"
    sound_ref="$(os_ref "$panel" Sound)"
    if [ -z "$sound_ref" ]; then
        badmsg "clicking Control Center did not return a panel snapshot with a Sound button  [ok=$(json_field "$panel" ok) error=$(json_field "$panel" error.code)]"
        return
    fi
    detail="$("$bin" click "$sound_ref" --wait-for "slider:sound volume" 2>/dev/null)"
    slider_ref="$(os_ref "$detail" "sound volume")"
    if [ -z "$slider_ref" ]; then
        badmsg "clicking Sound did not return a snapshot with the sound volume slider  [ok=$(json_field "$detail" ok) error=$(json_field "$detail" error.code)]"
        return
    fi
    set_output="$("$bin" set-value "$slider_ref" 0.5 2>/dev/null)"
    volume="$(os_wait_volume)" && volume_moved=1
    assert "set-value on the Control Center slider moves the system volume to about 50" \
        "$([ "$(json_field "$set_output" ok)" = "True" ] && [ "$volume_moved" = "1" ] && echo 1 || echo 0)" \
        "ok=$(json_field "$set_output" ok) error=$(json_field "$set_output" error.code) volume=$volume"
    os_close_panel || badmsg "clicking the Control Center item again did not close its panel"
    os_panel_open=1
    panel="$("$bin" --headed click "$os_cc_ref" 2>/dev/null)"
    assert "--headed click on the Control Center item opens its panel" \
        "$(os_wait_panel open && echo 1 || echo 0)" \
        "ok=$(json_field "$panel" ok) error=$(json_field "$panel" error.code)"
}

note "OS surfaces: process-name app, Dock, menu bar extras"
control_center_process="$("$bin" snapshot --app ControlCenter -i 2>/dev/null)"
assert "--app accepts the executable name ControlCenter without a window" \
    "$([ "$(json_field "$control_center_process" ok)" = "True" ] && \
        [ "$(json_field "$control_center_process" data.app)" = "Control Center" ] && \
        [ -z "$(json_field "$control_center_process" data.window)" ] && echo 1 || echo 0)" \
    "ok=$(json_field "$control_center_process" ok) app=$(json_field "$control_center_process" data.app) window=$(json_field "$control_center_process" data.window) error=$(json_field "$control_center_process" error.code)"

dock_surface="$("$bin" snapshot --surface dock -i 2>/dev/null)"
dock_process="$("$bin" snapshot --app Dock -i 2>/dev/null)"
assert "snapshot --surface dock lists the Dock items" \
    "$([ -n "$(os_ref "$dock_surface" Finder)" ] && echo 1 || echo 0)" \
    "ok=$(json_field "$dock_surface" ok) error=$(json_field "$dock_surface" error.code)"
assert "snapshot --app Dock lists the Dock items" \
    "$([ -n "$(os_ref "$dock_process" Finder)" ] && echo 1 || echo 0)" \
    "ok=$(json_field "$dock_process" ok) error=$(json_field "$dock_process" error.code)"

dock_launch=""
for candidate in TextEdit Calculator Notes; do
    if ! pgrep -x "$candidate" >/dev/null 2>&1 && [ -n "$(os_ref "$dock_surface" "$candidate")" ]; then
        dock_launch="$candidate"
        break
    fi
done
if [ -z "$dock_launch" ]; then
    skipmsg "Dock launch of a stopped app unavailable: no stopped TextEdit, Calculator or Notes item is pinned in the Dock"
else
    dock_click="$("$bin" click "$(os_ref "$dock_surface" "$dock_launch")" 2>/dev/null)"
    dock_launched=0
    for _ in $(seq 1 50); do
        if pgrep -x "$dock_launch" >/dev/null 2>&1; then dock_launched=1; break; fi
        sleep 0.2
    done
    assert "clicking the Dock item of a stopped app launches it" \
        "$([ "$(json_field "$dock_click" ok)" = "True" ] && [ "$dock_launched" = "1" ] && echo 1 || echo 0)" \
        "app=$dock_launch ok=$(json_field "$dock_click" ok) error=$(json_field "$dock_click" error.code) running=$dock_launched"
    "$bin" close-app "$dock_launch" --force >/dev/null 2>&1
fi

volume_original="$(os_volume)"
case "$volume_original" in
    ''|*[!0-9]*)
        badmsg "system output volume is not readable through osascript  [volume='$volume_original']"
        ;;
    *)
        trap 'os_restore_volume; cleanup' EXIT
        trap 'exit 130' INT TERM HUP
        osascript -e "set volume output volume 20" >/dev/null 2>&1
        os_control_center_volume
        os_restore_volume
        volume_restored="$(os_volume)"
        assert "the system output volume is restored after the scenario" \
            "$([ "$volume_restored" = "$volume_original" ] && echo 1 || echo 0)" \
            "volume=$volume_restored expected=$volume_original"
        trap cleanup EXIT
        trap - INT TERM HUP
        ;;
esac
