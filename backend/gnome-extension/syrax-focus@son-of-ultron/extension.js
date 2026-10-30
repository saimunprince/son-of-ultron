// SYRAX focus: the title and app class of the window in front, for SYRAX's desktop tool on GNOME (Wayland), where
// no ordinary program may ask which window has focus. One read-only D-Bus method, nothing else.
import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `<node><interface name="org.syrax.Focus">
  <method name="Focused"><arg type="s" direction="out" name="json"/></method>
</interface></node>`;

export default class SyraxFocus extends Extension {
    enable() {
        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._impl.export(Gio.DBus.session, '/org/syrax/Focus');
        this._owner = Gio.bus_own_name(Gio.BusType.SESSION, 'org.syrax.Focus', Gio.BusNameOwnerFlags.NONE, null, null, null);
    }

    disable() {
        this._impl?.unexport();
        this._impl = null;
        if (this._owner) {
            Gio.bus_unown_name(this._owner);
            this._owner = 0;
        }
    }

    Focused() {
        const w = global.display.focus_window;
        const json = JSON.stringify(w ? {title: w.get_title() ?? '', wm_class: w.get_wm_class() ?? ''} : null);
        // ASCII only (\uXXXX for the rest), so gdbus's text form reads back exactly
        return json.replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
    }
}
