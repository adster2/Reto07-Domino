$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface ICreateDevEnum {
 [PreserveSig] int CreateClassEnumerator(ref Guid category, out IEnumMoniker result, int flags);
}
[ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyBag {
 [PreserveSig] int Read([MarshalAs(UnmanagedType.LPWStr)] string name, [MarshalAs(UnmanagedType.Struct)] out object value, IntPtr log);
 [PreserveSig] int Write([MarshalAs(UnmanagedType.LPWStr)] string name, ref object value);
}
public class VideoSources {
 public static string[] Names() {
  var names = new List<string>();
  object instance = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
  IEnumMoniker enumerator = null;
  try {
   Guid category = new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
   int hr = ((ICreateDevEnum)instance).CreateClassEnumerator(ref category, out enumerator, 0);
   if(hr == 1) return names.ToArray();
   Marshal.ThrowExceptionForHR(hr);
   var items = new IMoniker[1];
   while(enumerator.Next(1, items, IntPtr.Zero) == 0) {
    object bag = null;
    try {
     Guid iid = new Guid("55272A00-42CB-11CE-8135-00AA004BB851");
     items[0].BindToStorage(null, null, ref iid, out bag);
     object name;
     Marshal.ThrowExceptionForHR(((IPropertyBag)bag).Read("FriendlyName", out name, IntPtr.Zero));
     names.Add((string)name);
    } finally {
     if(bag != null) Marshal.ReleaseComObject(bag);
     Marshal.ReleaseComObject(items[0]);
    }
   }
   return names.ToArray();
  } finally {
   if(enumerator != null) Marshal.ReleaseComObject(enumerator);
   Marshal.ReleaseComObject(instance);
  }
 }
}
"@
ConvertTo-Json -InputObject @([VideoSources]::Names()) -Compress
