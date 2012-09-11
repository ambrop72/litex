import math
import inspect
import re
from collections import defaultdict

from migen.fhdl import tracer

def log2_int(n):
	l = 1
	r = 0
	while l < n:
		l *= 2
		r += 1
	if l == n:
		return r
	else:
		raise ValueError("Not a power of 2")

def bits_for(n):
	if isinstance(n, Constant):
		return len(n)
	else:
		if n < 0:
			return bits_for(-n) + 1
		elif n == 0:
			return 1
		else:
			return int(math.ceil(math.log(n+1, 2)))

class BV:
	def __init__(self, width=1, signed=False):
		self.width = width
		self.signed = signed
	
	def __repr__(self):
		r = str(self.width) + "'"
		if self.signed:
			r += "s"
		r += "d"
		return r
	
	def __eq__(self, other):
		return self.width == other.width and self.signed == other.signed

class Value:
	def __invert__(self):
		return _Operator("~", [self])

	def __add__(self, other):
		return _Operator("+", [self, other])
	def __radd__(self, other):
		return _Operator("+", [other, self])
	def __sub__(self, other):
		return _Operator("-", [self, other])
	def __rsub__(self, other):
		return _Operator("-", [other, self])
	def __mul__(self, other):
		return _Operator("*", [self, other])
	def __rmul__(self, other):
		return _Operator("*", [other, self])
	def __lshift__(self, other):
		return _Operator("<<", [self, other])
	def __rlshift__(self, other):
		return _Operator("<<", [other, self])
	def __rshift__(self, other):
		return _Operator(">>", [self, other])
	def __rrshift__(self, other):
		return _Operator(">>", [other, self])
	def __and__(self, other):
		return _Operator("&", [self, other])
	def __rand__(self, other):
		return _Operator("&", [other, self])
	def __xor__(self, other):
		return _Operator("^", [self, other])
	def __rxor__(self, other):
		return _Operator("^", [other, self])
	def __or__(self, other):
		return _Operator("|", [self, other])
	def __ror__(self, other):
		return _Operator("|", [other, self])
	
	def __lt__(self, other):
		return _Operator("<", [self, other])
	def __le__(self, other):
		return _Operator("<=", [self, other])
	def __eq__(self, other):
		return _Operator("==", [self, other])
	def __ne__(self, other):
		return _Operator("!=", [self, other])
	def __gt__(self, other):
		return _Operator(">", [self, other])
	def __ge__(self, other):
		return _Operator(">=", [self, other])
	
	
	def __getitem__(self, key):
		if isinstance(key, int):
			return _Slice(self, key, key+1)
		elif isinstance(key, slice):
			start = key.start or 0
			stop = key.stop or len(self)
			if stop > len(self):
				stop = len(self)
			if key.step != None:
				raise KeyError
			return _Slice(self, start, stop)
		else:
			raise KeyError
	
	def eq(self, r):
		return _Assign(self, r)

class _Operator(Value):
	def __init__(self, op, operands):
		self.op = op
		self.operands = list(map(_cst, operands))

class _Slice(Value):
	def __init__(self, value, start, stop):
		self.value = value
		self.start = start
		self.stop = stop

class Cat(Value):
	def __init__(self, *args):
		self.l = list(map(_cst, args))

class Replicate(Value):
	def __init__(self, v, n):
		self.v = _cst(v)
		self.n = n

class Constant(Value):
	def __init__(self, n, bv=None):
		self.bv = bv or BV(bits_for(n), n < 0)
		self.n = n
	
	def __len__(self):
		return self.bv.width
	
	def __repr__(self):
		return str(self.bv) + str(self.n)
	
	def __eq__(self, other):
		return self.bv == other.bv and self.n == other.n

def binc(x, signed=False):
	return Constant(int(x, 2), BV(len(x), signed))

def _cst(x):
	if isinstance(x, int):
		return Constant(x)
	else:
		return x

class Signal(Value):
	_counter = 0
	def __init__(self, bv=BV(), name=None, variable=False, reset=0, name_override=None):
		assert(isinstance(bv, BV))
		self.bv = bv
		self.variable = variable
		self.reset = Constant(reset, bv)
		self.name_override = name_override
		self.backtrace = tracer.trace_back(name)
		self.order = Signal._counter
		Signal._counter += 1

	def __len__(self):
		return self.bv.width

	def __hash__(self):
		return id(self)
	
	def __repr__(self):
		return "<Signal " + (self.backtrace[-1][0] or "anonymous") + " at " + hex(id(self)) + ">"

# statements

class _Assign:
	def __init__(self, l, r):
		self.l = l
		self.r = _cst(r)

class If:
	def __init__(self, cond, *t):
		self.cond = cond
		self.t = list(t)
		self.f = []
	
	def Else(self, *f):
		_insert_else(self, list(f))
		return self
	
	def Elif(self, cond, *t):
		_insert_else(self, [If(cond, *t)])
		return self

def _insert_else(obj, clause):
	o = obj
	while o.f:
		assert(len(o.f) == 1)
		assert(isinstance(o.f[0], If))
		o = o.f[0]
	o.f = clause

class Default:
	pass

class Case:
	def __init__(self, test, *cases):
		self.test = test
		self.cases = [(c[0], list(c[1:])) for c in cases if not isinstance(c[0], Default)]
		self.default = None
		for c in cases:
			if isinstance(c[0], Default):
				if self.default is not None:
					raise ValueError
				self.default = list(c[1:])
		if self.default is None:
			self.default = []

# arrays

class _ArrayProxy(Value):
	def __init__(self, choices, key):
		self.choices = choices
		self.key = key
	
	def __getattr__(self, attr):
		return _ArrayProxy([getattr(choice, attr) for choice in self.choices],
			self.key)
	
	def __getitem__(self, key):
		return _ArrayProxy([choice.__getitem__(key) for choice in self.choices],
			self.key)

class Array(list):
	def __getitem__(self, key):
		if isinstance(key, Value):
			return _ArrayProxy(self, key)
		else:
			return super().__getitem__(key)

# extras

class Instance:
	def __init__(self, of, *items, name=""):
		self.of = of
		if name:
			self.name_override = name
		else:
			self.name_override = of
		self.items = items
	
	class _IO:
		def __init__(self, name, signal_or_bv):
			self.name = name
			if isinstance(signal_or_bv, Signal):
				self.signal = signal_or_bv
			elif isinstance(signal_or_bv, BV):
				self.signal = Signal(signal_or_bv, name)
			else:
				raise TypeError
	class Input(_IO):
		pass	
	class Output(_IO):
		pass
	class InOut(_IO):
		pass

	class Parameter:
		def __init__(self, name, value):
			self.name = name
			self.value = value
	
	class _CR:
		def __init__(self, name_inst, domain="sys"):
			self.name_inst = name_inst
			self.domain = domain
	class ClockPort(_CR):
		pass
	class ResetPort(_CR):
		pass
	
	def get_io(self, name):
		for item in self.items:
			if isinstance(item, Instance._IO) and item.name == name:
				return item.signal
	
	def __hash__(self):
		return id(self)

(READ_FIRST, WRITE_FIRST, NO_CHANGE) = range(3)

class MemoryPort:
	def __init__(self, adr, dat_r, we=None, dat_w=None,
	  async_read=False, re=None, we_granularity=0, mode=WRITE_FIRST,
	  clock_domain="sys"):
		self.adr = adr
		self.dat_r = dat_r
		self.we = we
		self.dat_w = dat_w
		self.async_read = async_read
		self.re = re
		self.we_granularity = we_granularity
		self.mode = mode
		self.clock_domain = clock_domain

class Memory:
	def __init__(self, width, depth, *ports, init=None):
		self.width = width
		self.depth = depth
		self.ports = ports
		self.init = init

#

class Fragment:
	def __init__(self, comb=None, sync=None, instances=None, memories=None, sim=None):
		if comb is None: comb = []
		if sync is None: sync = dict()
		if instances is None: instances = []
		if memories is None: memories = []
		if sim is None: sim = []
		
		if isinstance(sync, list):
			sync = {"sys": sync}
		
		self.comb = comb
		self.sync = sync
		self.instances = instances
		self.memories = memories
		self.sim = sim
		
	
	def __add__(self, other):
		newsync = defaultdict(list)
		for k, v in self.sync.items():
			newsync[k] = v[:]
		for k, v in other.sync.items():
			newsync[k].extend(v)
		return Fragment(self.comb + other.comb, newsync,
			self.instances + other.instances,
			self.memories + other.memories,
			self.sim + other.sim)
	
	def rename_clock_domain(self, old, new):
		self.sync["new"] = self.sync["old"]
		del self.sync["old"]
		for inst in self.instances:
			for cr in filter(lambda x: isinstance(x, Instance._CR), inst.items):
				if cr.domain == old:
					cr.domain = new
		for mem in self.memories:
			for port in mem.ports:
				if port.clock_domain == old:
					port.clock_domain = new

	def get_clock_domains(self):
		r = set(self.sync.keys())
		r |= set(cr.domain 
			for inst in self.instances
			for cr in filter(lambda x: isinstance(x, Instance._CR), inst.items))
		r |= set(port.clock_domain
			for mem in self.memories
			for port in mem.ports)
		return r
	
	def call_sim(self, simulator):
		for s in self.sim:
			if simulator.cycle_counter >= 0 or (hasattr(s, "initialize") and s.initialize):
				s(simulator)

class ClockDomain:
	def __init__(self, n1, n2=None):
		if n2 is None:
			n_clk = n1 + "_clk"
			n_rst = n1 + "_rst"
		else:
			n_clk = n1
			n_rst = n2
		self.clk = Signal(name_override=n_clk)
		self.rst = Signal(name_override=n_rst)
