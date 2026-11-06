import com.cburch.logisim.circuit.*;
import com.cburch.logisim.comp.*;
import com.cburch.logisim.data.*;
import com.cburch.logisim.instance.*;
import com.cburch.logisim.proj.*;
import com.cburch.logisim.std.wiring.Pin;
import java.io.*;
import java.lang.reflect.Method;
import java.util.*;

/** Runs the whole CPU (circuit PC) until its halt pin goes to 1 and prints, from the RAM
 *  subcircuit's state: the stack limit (the register at (730,520) holds it inverted), EBP,
 *  ESP and the LIMIT_HIT pin (1110,540).
 *
 *  java LimitProbe patched.circ [max cycles]
 *
 *  Prints "limit=0x.. ebp=0x.. esp=0x.. hit=0|1 cycles=N" at cycle 40 (after the reset, before
 *  the start-up code reaches SLIM) and at HALT. Locations are those of CPU.circ's RAM circuit. */
public class LimitProbe {
  static CircuitState find(CircuitState s, String name) {
    if (s.getCircuit().getName().equals(name)) return s;
    for (CircuitState sub : s.getSubstates()) { CircuitState r = find(sub, name); if (r != null) return r; }
    return null;
  }

  static CircuitState findRam(CircuitState s) { return find(s, "RAM"); }

  /** CONTROL_SECTION's pins that are high or undefined: which control lines are active now. */
  static String controls(CircuitState root) {
    CircuitState cs = find(root, "CONTROL_SECTION");
    StringBuilder b = new StringBuilder();
    for (Component c : cs.getCircuit().getNonWires()) {
      if (!(c.getFactory() instanceof Pin)) continue;
      Value v = Pin.FACTORY.getValue(cs.getInstanceState(c));
      String l = c.getAttributeSet().getValue(StdAttr.LABEL);
      String n = (l == null || l.isEmpty()) ? c.getLocation().toString().replace(" ", "") : l;
      if (!v.isFullyDefined()) b.append(n).append("=").append(v).append(" ");
      else if (v.toLongValue() != 0) b.append(n).append("=").append(Long.toHexString(v.toLongValue())).append(" ");
    }
    return b.toString();
  }

  static Component at(Circuit c, String loc) {
    for (Component k : c.getNonWires()) if (k.getLocation().toString().replace(" ", "").equals(loc)) return k;
    throw new RuntimeException("nothing at " + loc + " in " + c.getName());
  }

  static String reg(CircuitState ram, String loc) throws Exception {
    InstanceData d = ram.getInstanceState(at(ram.getCircuit(), loc)).getData();
    if (d == null) return "?";
    Method m = d.getClass().getMethod("getValue");
    m.setAccessible(true);
    Value v = (Value) m.invoke(d);
    return v.isFullyDefined() ? String.format("0x%06x", v.toLongValue()) : v.toString();
  }

  static String report(CircuitState root) throws Exception {
    CircuitState ram = findRam(root);
    Value hit = Pin.FACTORY.getValue(ram.getInstanceState(at(ram.getCircuit(), "(1110,540)")));
    String lim = reg(ram, "(730,520)");
    if (lim.startsWith("0x")) lim = String.format("0x%06x", ~Long.decode(lim) & 0xFFFFFF);
    return "limit=" + lim + " ebp=" + reg(ram, "(730,640)") + " esp=" + reg(ram, "(730,820)")
        + " hit=" + (hit.isFullyDefined() ? hit.toLongValue() : "?");
  }

  public static void main(String[] a) throws Exception {
    Project p = ProjectActions.doOpenNoWindow(null, new File(a[0]));
    long max = a.length > 1 ? Long.parseLong(a[1]) : 400000;
    CircuitState st = CircuitState.createRootState(p, p.getLogisimFile().getCircuit("PC"), Thread.currentThread());
    Propagator prop = st.getPropagator();
    Component halt = null;
    for (Component c : st.getCircuit().getNonWires())
      if (c.getFactory() instanceof Pin && "halt".equals(c.getAttributeSet().getValue(StdAttr.LABEL))) halt = c;
    if (halt == null) throw new RuntimeException("no pin labelled halt in PC");
    for (long n = 1; n <= max; n++) {
      prop.toggleClocks(); prop.propagate();
      prop.toggleClocks(); prop.propagate();
      if (prop.isOscillating()) { System.out.println("OSCILLATING at cycle " + n + ": " + report(st)); System.exit(2); }
      if (n == 40) System.out.println("cycle 40: " + report(st));
      Value h = Pin.FACTORY.getValue(st.getInstanceState(halt));
      if (h.isFullyDefined() && h.toLongValue() == 1) {
        System.out.println("halted: " + report(st) + " cycles=" + n);
        System.exit(0);
      }
    }
    System.out.println("no halt in " + max + " cycles: " + report(st));
    System.out.println("control lines now: " + controls(st));
    System.exit(1);
  }
}
