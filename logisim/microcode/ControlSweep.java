import com.cburch.logisim.circuit.*;
import com.cburch.logisim.comp.*;
import com.cburch.logisim.data.*;
import com.cburch.logisim.instance.*;
import com.cburch.logisim.proj.*;
import com.cburch.logisim.std.wiring.Pin;
import java.io.*;
import java.util.*;

/** Runs CONTROL_SECTION of a probe circuit (made by verify.py) through Logisim's own
 *  simulator for every IR (16 bits), step (4) and flag value (4).
 *
 *  java ControlSweep probe.circ out.bin [pin=hex ...]
 *
 *  Input pins start at 0; P_CLK0, P_CLK1, P_CLK2, P_STEPBIT and CLK at 1; the arguments
 *  override them. Writes out.bin.names (the output pins, 1-bit ones first, then the wider
 *  ones, each group by name) and out.bin: per point, in the order IR, step, flags (flags
 *  fastest, flag pins from top to bottom as bits 0..3), big-endian ints: the 1-bit outputs at
 *  1, the 1-bit outputs not 0 or 1, then one int per wider output (-1 if a bit is not 0/1). */
public class ControlSweep {
  static CircuitState st;

  static String name(Component c) {
    String l = c.getAttributeSet().getValue(StdAttr.LABEL);
    return (l == null || l.isEmpty()) ? "pin" + c.getLocation().toString().replace(" ", "") : l;
  }

  static void drive(Component c, long v) {
    int w = c.getEnd(0).getWidth().getWidth();
    Pin.FACTORY.driveInputPin(st.getInstanceState(c), Value.createKnown(BitWidth.create(w), v));
    st.markComponentAsDirty(c);
  }

  public static void main(String[] a) throws Exception {
    Project p = ProjectActions.doOpenNoWindow(null, new File(a[0]));
    Circuit c = p.getLogisimFile().getCircuit("CONTROL_SECTION");
    st = CircuitState.createRootState(p, c, Thread.currentThread());
    Propagator prop = st.getPropagator();
    Map<String, Component> ins = new TreeMap<>(), outs = new TreeMap<>();
    for (Component comp : c.getNonWires()) {
      if (!(comp.getFactory() instanceof Pin)) continue;
      boolean in = Pin.FACTORY.isInputPin(((InstanceComponent) comp).getInstance());
      (in ? ins : outs).put(name(comp), comp);
    }
    List<Component> one = new ArrayList<>(), wide = new ArrayList<>();
    try (PrintWriter w = new PrintWriter(a[1] + ".names")) {
      for (var e : outs.entrySet())
        if (e.getValue().getEnd(0).getWidth().getWidth() == 1) { one.add(e.getValue()); w.println(e.getKey()); }
      for (var e : outs.entrySet())
        if (e.getValue().getEnd(0).getWidth().getWidth() > 1) { wide.add(e.getValue()); w.println(e.getKey()); }
    }
    if (one.size() > 32) throw new RuntimeException("more than 32 one-bit outputs");
    for (Component in : ins.values()) drive(in, 0);
    for (String k : new String[] {"P_CLK0", "P_CLK1", "P_CLK2", "P_STEPBIT", "CLK"}) drive(ins.get(k), 1);
    for (int i = 2; i < a.length; i++) {
      String[] kv = a[i].split("=");
      drive(ins.get(kv[0]), Long.parseLong(kv[1], 16));
    }
    Component irP = ins.get("pin(1020,2550)"), stepP = ins.get("P_STEP");
    Component[] fl = {ins.get("pin(460,1970)"), ins.get("pin(460,2010)"),
                      ins.get("pin(460,2050)"), ins.get("pin(460,2090)")};
    long osc = 0;
    try (DataOutputStream out = new DataOutputStream(new BufferedOutputStream(new FileOutputStream(a[1]), 1 << 20))) {
      for (int ir = 0; ir < 0x10000; ir++) {
        drive(irP, ir);
        for (int step = 0; step < 16; step++) {
          drive(stepP, step);
          for (int f = 0; f < 16; f++) {
            for (int i = 0; i < 4; i++) drive(fl[i], (f >> i) & 1);
            prop.propagate();
            if (prop.isOscillating()) osc++;
            int ones = 0, undef = 0;
            for (int i = 0; i < one.size(); i++) {
              Value v = Pin.FACTORY.getValue(st.getInstanceState(one.get(i)));
              if (!v.isFullyDefined()) undef |= 1 << i;
              else if (v.toLongValue() != 0) ones |= 1 << i;
            }
            out.writeInt(ones);
            out.writeInt(undef);
            for (Component m : wide) {
              Value v = Pin.FACTORY.getValue(st.getInstanceState(m));
              out.writeInt(v.isFullyDefined() ? (int) v.toLongValue() : -1);
            }
          }
        }
      }
    }
    System.out.println("oscillating points: " + osc);
    System.exit(0);
  }
}
