param([string]$Set = "")
$code = @'
using System;
using System.Runtime.InteropServices;
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
[Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection { int GetCount(out int count); int Item(int index, out IMMDevice device); }
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid iid, int clsCtx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); int OpenPropertyStore(int access, out IPropertyStore store); int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetState(out int state); }
[Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore { int GetCount(out int c); int GetAt(int i, out PROPERTYKEY k); int GetValue(ref PROPERTYKEY k, out PROPVARIANT v); }
[StructLayout(LayoutKind.Sequential)] struct PROPERTYKEY { public Guid fmtid; public int pid; }
[StructLayout(LayoutKind.Sequential)] struct PROPVARIANT { public short vt; short r1, r2, r3; public IntPtr p; public IntPtr p2; }
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume { int RegisterControlChangeNotify(IntPtr n); int UnregisterControlChangeNotify(IntPtr n); int GetChannelCount(out int c);
 int SetMasterVolumeLevel(float l, ref Guid g); int SetMasterVolumeLevelScalar(float l, ref Guid g); int GetMasterVolumeLevel(out float l); int GetMasterVolumeLevelScalar(out float l);
 int SetChannelVolumeLevel(int c, float l, ref Guid g); int SetChannelVolumeLevelScalar(int c, float l, ref Guid g); int GetChannelVolumeLevel(int c, out float l); int GetChannelVolumeLevelScalar(int c, out float l);
 int SetMute(bool m, ref Guid g); int GetMute(out bool m); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}
public static class AudioInfo {
  public static string SetDefaultOut(float level, bool mute) { var e = (IMMDeviceEnumerator)new MMDeviceEnumerator(); IMMDevice d; e.GetDefaultAudioEndpoint(0, 1, out d);
    var iid = typeof(IAudioEndpointVolume).GUID; object o; d.Activate(ref iid, 23, IntPtr.Zero, out o); var ev = (IAudioEndpointVolume)o; var g = Guid.Empty;
    ev.SetMasterVolumeLevelScalar(level, ref g); ev.SetMute(mute, ref g); return Name(d) + " | " + Vol(d); }
  static string Name(IMMDevice d) { IPropertyStore s; d.OpenPropertyStore(0, out s); var k = new PROPERTYKEY { fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"), pid = 14 }; PROPVARIANT v; s.GetValue(ref k, out v); return Marshal.PtrToStringUni(v.p); }
  static string Vol(IMMDevice d) { var iid = typeof(IAudioEndpointVolume).GUID; object o; d.Activate(ref iid, 23, IntPtr.Zero, out o); var ev = (IAudioEndpointVolume)o; float l; bool m; ev.GetMasterVolumeLevelScalar(out l); ev.GetMute(out m); return "volume=" + Math.Round(l * 100) + "% mute=" + m; }
  public static string Report() {
    var e = (IMMDeviceEnumerator)new MMDeviceEnumerator(); var sb = new System.Text.StringBuilder();
    foreach (var flow in new[] { 0, 1 }) {
      IMMDevice def; e.GetDefaultAudioEndpoint(flow, 1, out def); string defId; def.GetId(out defId);
      IMMDeviceCollection c; e.EnumAudioEndpoints(flow, 1, out c); int n; c.GetCount(out n);
      for (int i = 0; i < n; i++) { IMMDevice d; c.Item(i, out d); string id; d.GetId(out id);
        sb.AppendLine((flow == 0 ? "OUT " : "IN  ") + (id == defId ? "[default] " : "          ") + Name(d) + " | " + Vol(d)); }
    }
    return sb.ToString();
  }
}
'@
Add-Type -TypeDefinition $code
if ($Set) { $l, $m = $Set.Split(","); [AudioInfo]::SetDefaultOut([float]$l / 100, $m -eq "mute") } else { [AudioInfo]::Report() }
