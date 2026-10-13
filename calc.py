"""Exact arithmetic for Piper. Language models are unreliable at maths, so Piper never lets the brain do sums:
- plain sums ("what's 245 x 18") are answered here instantly, without the brain;
- in normal answers the brain writes [CALC: expression] and Piper replaces it with the exact result.
Only arithmetic is allowed (no code, no names), so it is safe to evaluate.
"""
import ast, math, operator, re

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCS = {"ceil": math.ceil, "floor": math.floor, "round": round, "sqrt": math.sqrt, "abs": abs, "min": min, "max": max,
         "roundup": math.ceil, "rounddown": math.floor}

def _eval(n):
    if isinstance(n, ast.Expression): return _eval(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in OPS:
        a, b = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 100: raise ValueError("power too large")
        return OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in OPS: return OPS[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
        return FUNCS[n.func.id](*[_eval(a) for a in n.args])
    raise ValueError("not arithmetic")

def normalise(expr):
    e = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", expr.lower()).replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    e = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"\1/100*", e)          # 15% of 80
    e = re.sub(r"(\d)\s*x\s*(\d)", r"\1*\2", e)                         # 12 x 5
    for w, s in (("multiplied by", "*"), ("times", "*"), ("divided by", "/"), ("over", "/"), ("plus", "+"), ("minus", "-"),
                 ("squared", "**2"), ("cubed", "**3")):
        e = re.sub(rf"\b{w}\b", s, e)
    e = re.sub(r"(\d)\s*x\s*\(", r"\1*(", e)
    return e.strip()

def evaluate(expr):
    v = _eval(ast.parse(normalise(expr), mode="eval"))
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)): raise ValueError("no answer")
    return v

def fmt(v):
    """Readable: thousands separators, no needless decimals."""
    if isinstance(v, float) and v.is_integer(): v = int(v)
    if isinstance(v, int): return f"{v:,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) >= 1 else f"{v:.4g}"

TAG = re.compile(r"\[\s*CALC\s*:\s*([^\]]+?)\s*\]", re.I)

def fill(text):
    """Replace every [CALC: ...] the brain wrote with the exact result."""
    def rep(m):
        try: return fmt(evaluate(m.group(1)))
        except Exception: return "(I couldn't work that sum out)"
    return TAG.sub(rep, text)

SUM = re.compile(r"^(?:(?:hey |ok )?piper[, ]*)?(?:what(?:'s| is)|calculate|work out|how much is|compute|whats)?\s*([\d\s.,+\-*/x×÷()%^]+(?:\s*(?:times|plus|minus|divided by|multiplied by|over|squared|cubed|% of)\s*[\d\s.,+\-*/x×÷()%^]*)*)\s*[?.!]*$", re.I)

def direct(text):
    """A plain sum on its own ('what's 245 x 18?'): exact answer, no brain needed."""
    m = SUM.match(text.strip())
    if not m or not re.search(r"\d\s*(?:[+\-*/x×÷^%]|times|plus|minus|divided|multiplied|over|squared|cubed)", m.group(1), re.I): return None
    try: return f"{m.group(1).strip().rstrip('?')} is {fmt(evaluate(m.group(1)))}."
    except Exception: return None
