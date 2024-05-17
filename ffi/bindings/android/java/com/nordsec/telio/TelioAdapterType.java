/* ----------------------------------------------------------------------------
 * This file was automatically generated by SWIG (http://www.swig.org).
 * Version 4.0.2
 *
 * Do not make changes to this file unless you know what you are doing--modify
 * the SWIG interface file instead.
 * ----------------------------------------------------------------------------- */

package com.nordsec.telio;

public final class TelioAdapterType {
  public final static TelioAdapterType ADAPTER_BORING_TUN = new TelioAdapterType("ADAPTER_BORING_TUN");
  public final static TelioAdapterType ADAPTER_LINUX_NATIVE_TUN = new TelioAdapterType("ADAPTER_LINUX_NATIVE_TUN");
  public final static TelioAdapterType ADAPTER_WIREGUARD_GO_TUN = new TelioAdapterType("ADAPTER_WIREGUARD_GO_TUN");
  public final static TelioAdapterType ADAPTER_WINDOWS_NATIVE_TUN = new TelioAdapterType("ADAPTER_WINDOWS_NATIVE_TUN");

  public final int swigValue() {
    return swigValue;
  }

  public String toString() {
    return swigName;
  }

  public static TelioAdapterType swigToEnum(int swigValue) {
    if (swigValue < swigValues.length && swigValue >= 0 && swigValues[swigValue].swigValue == swigValue)
      return swigValues[swigValue];
    for (int i = 0; i < swigValues.length; i++)
      if (swigValues[i].swigValue == swigValue)
        return swigValues[i];
    throw new IllegalArgumentException("No enum " + TelioAdapterType.class + " with value " + swigValue);
  }

  private TelioAdapterType(String swigName) {
    this.swigName = swigName;
    this.swigValue = swigNext++;
  }

  private TelioAdapterType(String swigName, int swigValue) {
    this.swigName = swigName;
    this.swigValue = swigValue;
    swigNext = swigValue+1;
  }

  private TelioAdapterType(String swigName, TelioAdapterType swigEnum) {
    this.swigName = swigName;
    this.swigValue = swigEnum.swigValue;
    swigNext = this.swigValue+1;
  }

  private static TelioAdapterType[] swigValues = { ADAPTER_BORING_TUN, ADAPTER_LINUX_NATIVE_TUN, ADAPTER_WIREGUARD_GO_TUN, ADAPTER_WINDOWS_NATIVE_TUN };
  private static int swigNext = 0;
  private final int swigValue;
  private final String swigName;
}
