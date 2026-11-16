import { bytes as e, networkStore as t } from "./store.mjs";
//#region node_modules/@vue/shared/dist/shared.esm-bundler.js
// @__NO_SIDE_EFFECTS__
function n(e) {
	let t = /* @__PURE__ */ Object.create(null);
	for (let n of e.split(",")) t[n] = 1;
	return (e) => e in t;
}
var r = {}, i = [], a = () => {}, o = () => !1, s = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && (e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97), c = (e) => e.startsWith("onUpdate:"), l = Object.assign, u = (e, t) => {
	let n = e.indexOf(t);
	n > -1 && e.splice(n, 1);
}, d = Object.prototype.hasOwnProperty, f = (e, t) => d.call(e, t), p = Array.isArray, m = (e) => C(e) === "[object Map]", h = (e) => C(e) === "[object Set]", g = (e) => C(e) === "[object Date]", _ = (e) => typeof e == "function", v = (e) => typeof e == "string", y = (e) => typeof e == "symbol", b = (e) => typeof e == "object" && !!e, x = (e) => (b(e) || _(e)) && _(e.then) && _(e.catch), S = Object.prototype.toString, C = (e) => S.call(e), w = (e) => C(e).slice(8, -1), ee = (e) => C(e) === "[object Object]", T = (e) => v(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, te = /* @__PURE__ */ n(",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"), ne = (e) => {
	let t = /* @__PURE__ */ Object.create(null);
	return ((n) => t[n] || (t[n] = e(n)));
}, E = /-\w/g, D = ne((e) => e.replace(E, (e) => e.slice(1).toUpperCase())), re = /\B([A-Z])/g, ie = ne((e) => e.replace(re, "-$1").toLowerCase()), ae = ne((e) => e.charAt(0).toUpperCase() + e.slice(1)), oe = ne((e) => e ? `on${ae(e)}` : ""), O = (e, t) => !Object.is(e, t), se = (e, ...t) => {
	for (let n = 0; n < e.length; n++) e[n](...t);
}, ce = (e, t, n, r = !1) => {
	Object.defineProperty(e, t, {
		configurable: !0,
		enumerable: !1,
		writable: r,
		value: n
	});
}, le = (e) => {
	let t = parseFloat(e);
	return isNaN(t) ? e : t;
}, ue = (e) => {
	let t = v(e) ? Number(e) : NaN;
	return isNaN(t) ? e : t;
}, de, fe = () => de ||= typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {};
function pe(e) {
	if (p(e)) {
		let t = {};
		for (let n = 0; n < e.length; n++) {
			let r = e[n], i = v(r) ? _e(r) : pe(r);
			if (i) for (let e in i) t[e] = i[e];
		}
		return t;
	} else if (v(e) || b(e)) return e;
}
var me = /;(?![^(]*\))/g, he = /:([^]+)/, ge = /\/\*[^]*?\*\//g;
function _e(e) {
	let t = {};
	return e.replace(ge, "").split(me).forEach((e) => {
		if (e) {
			let n = e.split(he);
			n.length > 1 && (t[n[0].trim()] = n[1].trim());
		}
	}), t;
}
function k(e) {
	let t = "";
	if (v(e)) t = e;
	else if (p(e)) for (let n = 0; n < e.length; n++) {
		let r = k(e[n]);
		r && (t += r + " ");
	}
	else if (b(e)) for (let n in e) e[n] && (t += n + " ");
	return t.trim();
}
var ve = "itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,readonly", ye = /* @__PURE__ */ n(ve);
ve + "";
function be(e) {
	return !!e || e === "";
}
function xe(e, t) {
	if (e.length !== t.length) return !1;
	let n = !0;
	for (let r = 0; n && r < e.length; r++) n = Se(e[r], t[r]);
	return n;
}
function Se(e, t) {
	if (e === t) return !0;
	let n = g(e), r = g(t);
	if (n || r) return n && r ? e.getTime() === t.getTime() : !1;
	if (n = y(e), r = y(t), n || r) return e === t;
	if (n = p(e), r = p(t), n || r) return n && r ? xe(e, t) : !1;
	if (n = b(e), r = b(t), n || r) {
		if (!n || !r || Object.keys(e).length !== Object.keys(t).length) return !1;
		for (let n in e) {
			let r = e.hasOwnProperty(n), i = t.hasOwnProperty(n);
			if (r && !i || !r && i || !Se(e[n], t[n])) return !1;
		}
	}
	return String(e) === String(t);
}
function Ce(e, t) {
	return e.findIndex((e) => Se(e, t));
}
var we = (e) => !!(e && e.__v_isRef === !0), A = (e) => v(e) ? e : e == null ? "" : p(e) || b(e) && (e.toString === S || !_(e.toString)) ? we(e) ? A(e.value) : JSON.stringify(e, Te, 2) : String(e), Te = (e, t) => we(t) ? Te(e, t.value) : m(t) ? { [`Map(${t.size})`]: [...t.entries()].reduce((e, [t, n], r) => (e[Ee(t, r) + " =>"] = n, e), {}) } : h(t) ? { [`Set(${t.size})`]: [...t.values()].map((e) => Ee(e)) } : y(t) ? Ee(t) : b(t) && !p(t) && !ee(t) ? String(t) : t, Ee = (e, t = "") => y(e) ? `Symbol(${e.description ?? t})` : e, j, De = class {
	constructor(e = !1) {
		this.detached = e, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !e && j && (j.active ? (this.parent = j, this.index = (j.scopes ||= []).push(this) - 1) : (this._active = !1, this._warnOnRun = !1));
	}
	get active() {
		return this._active;
	}
	pause() {
		if (this._active) {
			this._isPaused = !0;
			let e, t;
			if (this.scopes) for (e = 0, t = this.scopes.length; e < t; e++) this.scopes[e].pause();
			for (e = 0, t = this.effects.length; e < t; e++) this.effects[e].pause();
		}
	}
	resume() {
		if (this._active && this._isPaused) {
			this._isPaused = !1;
			let e, t;
			if (this.scopes) for (e = 0, t = this.scopes.length; e < t; e++) this.scopes[e].resume();
			for (e = 0, t = this.effects.length; e < t; e++) this.effects[e].resume();
		}
	}
	run(e) {
		if (this._active) {
			let t = j;
			try {
				return j = this, e();
			} finally {
				j = t;
			}
		}
	}
	on() {
		++this._on === 1 && (this.prevScope = j, j = this);
	}
	off() {
		if (this._on > 0 && --this._on === 0) {
			if (j === this) j = this.prevScope;
			else {
				let e = j;
				for (; e;) {
					if (e.prevScope === this) {
						e.prevScope = this.prevScope;
						break;
					}
					e = e.prevScope;
				}
			}
			this.prevScope = void 0;
		}
	}
	stop(e) {
		if (this._active) {
			this._active = !1;
			let t, n;
			for (t = 0, n = this.effects.length; t < n; t++) this.effects[t].stop();
			for (this.effects.length = 0, t = 0, n = this.cleanups.length; t < n; t++) this.cleanups[t]();
			if (this.cleanups.length = 0, this.scopes) {
				for (t = 0, n = this.scopes.length; t < n; t++) this.scopes[t].stop(!0);
				this.scopes.length = 0;
			}
			if (!this.detached && this.parent && !e) {
				let e = this.parent.scopes.pop();
				e && e !== this && (this.parent.scopes[this.index] = e, e.index = this.index);
			}
			this.parent = void 0;
		}
	}
};
function Oe() {
	return j;
}
var M, ke = /* @__PURE__ */ new WeakSet(), Ae = class {
	constructor(e) {
		this.fn = e, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, j && (j.active ? j.effects.push(this) : this.flags &= -2);
	}
	pause() {
		this.flags |= 64;
	}
	resume() {
		this.flags & 64 && (this.flags &= -65, ke.has(this) && (ke.delete(this), this.trigger()));
	}
	notify() {
		this.flags & 2 && !(this.flags & 32) || this.flags & 8 || Pe(this);
	}
	run() {
		if (!(this.flags & 1)) return this.fn();
		this.flags |= 2, qe(this), Le(this);
		let e = M, t = Ue;
		M = this, Ue = !0;
		try {
			return this.fn();
		} finally {
			Re(this), M = e, Ue = t, this.flags &= -3;
		}
	}
	stop() {
		if (this.flags & 1) {
			for (let e = this.deps; e; e = e.nextDep) Ve(e);
			this.deps = this.depsTail = void 0, qe(this), this.onStop && this.onStop(), this.flags &= -2;
		}
	}
	trigger() {
		this.flags & 64 ? ke.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
	}
	runIfDirty() {
		ze(this) && this.run();
	}
	get dirty() {
		return ze(this);
	}
}, je = 0, Me, Ne;
function Pe(e, t = !1) {
	if (e.flags |= 8, t) {
		e.next = Ne, Ne = e;
		return;
	}
	e.next = Me, Me = e;
}
function Fe() {
	je++;
}
function Ie() {
	if (--je > 0) return;
	if (Ne) {
		let e = Ne;
		for (Ne = void 0; e;) {
			let t = e.next;
			e.next = void 0, e.flags &= -9, e = t;
		}
	}
	let e;
	for (; Me;) {
		let t = Me;
		for (Me = void 0; t;) {
			let n = t.next;
			if (t.next = void 0, t.flags &= -9, t.flags & 1) try {
				t.trigger();
			} catch (t) {
				e ||= t;
			}
			t = n;
		}
	}
	if (e) throw e;
}
function Le(e) {
	for (let t = e.deps; t; t = t.nextDep) t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function Re(e) {
	let t, n = e.depsTail, r = n;
	for (; r;) {
		let e = r.prevDep;
		r.version === -1 ? (r === n && (n = e), Ve(r), He(r)) : t = r, r.dep.activeLink = r.prevActiveLink, r.prevActiveLink = void 0, r = e;
	}
	e.deps = t, e.depsTail = n;
}
function ze(e) {
	for (let t = e.deps; t; t = t.nextDep) if (t.dep.version !== t.version || t.dep.computed && (Be(t.dep.computed) || t.dep.version !== t.version)) return !0;
	return !!e._dirty;
}
function Be(e) {
	if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === Je) || (e.globalVersion = Je, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !ze(e)))) return;
	e.flags |= 2;
	let t = e.dep, n = M, r = Ue;
	M = e, Ue = !0;
	try {
		Le(e);
		let n = e.fn(e._value);
		(t.version === 0 || O(n, e._value)) && (e.flags |= 128, e._value = n, t.version++);
	} catch (e) {
		throw t.version++, e;
	} finally {
		M = n, Ue = r, Re(e), e.flags &= -3;
	}
}
function Ve(e, t = !1) {
	let { dep: n, prevSub: r, nextSub: i } = e;
	if (r && (r.nextSub = i, e.prevSub = void 0), i && (i.prevSub = r, e.nextSub = void 0), n.subs === e && (n.subs = r, !r && n.computed)) {
		n.computed.flags &= -5;
		for (let e = n.computed.deps; e; e = e.nextDep) Ve(e, !0);
	}
	!t && !--n.sc && n.map && n.map.delete(n.key);
}
function He(e) {
	let { prevDep: t, nextDep: n } = e;
	t && (t.nextDep = n, e.prevDep = void 0), n && (n.prevDep = t, e.nextDep = void 0);
}
var Ue = !0, We = [];
function Ge() {
	We.push(Ue), Ue = !1;
}
function Ke() {
	let e = We.pop();
	Ue = e === void 0 ? !0 : e;
}
function qe(e) {
	let { cleanup: t } = e;
	if (e.cleanup = void 0, t) {
		let e = M;
		M = void 0;
		try {
			t();
		} finally {
			M = e;
		}
	}
}
var Je = 0, Ye = class {
	constructor(e, t) {
		this.sub = e, this.dep = t, this.version = t.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
	}
}, Xe = class {
	constructor(e) {
		this.computed = e, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
	}
	track(e) {
		if (!M || !Ue || M === this.computed) return;
		let t = this.activeLink;
		if (t === void 0 || t.sub !== M) t = this.activeLink = new Ye(M, this), M.deps ? (t.prevDep = M.depsTail, M.depsTail.nextDep = t, M.depsTail = t) : M.deps = M.depsTail = t, Ze(t);
		else if (t.version === -1 && (t.version = this.version, t.nextDep)) {
			let e = t.nextDep;
			e.prevDep = t.prevDep, t.prevDep && (t.prevDep.nextDep = e), t.prevDep = M.depsTail, t.nextDep = void 0, M.depsTail.nextDep = t, M.depsTail = t, M.deps === t && (M.deps = e);
		}
		return t;
	}
	trigger(e) {
		this.version++, Je++, this.notify(e);
	}
	notify(e) {
		Fe();
		try {
			for (let e = this.subs; e; e = e.prevSub) e.sub.notify() && e.sub.dep.notify();
		} finally {
			Ie();
		}
	}
};
function Ze(e) {
	if (e.dep.sc++, e.sub.flags & 4) {
		let t = e.dep.computed;
		if (t && !e.dep.subs) {
			t.flags |= 20;
			for (let e = t.deps; e; e = e.nextDep) Ze(e);
		}
		let n = e.dep.subs;
		n !== e && (e.prevSub = n, n && (n.nextSub = e)), e.dep.subs = e;
	}
}
var Qe = /* @__PURE__ */ new WeakMap(), $e = /* @__PURE__ */ Symbol(""), et = /* @__PURE__ */ Symbol(""), tt = /* @__PURE__ */ Symbol("");
function N(e, t, n) {
	if (Ue && M) {
		let t = Qe.get(e);
		t || Qe.set(e, t = /* @__PURE__ */ new Map());
		let r = t.get(n);
		r || (t.set(n, r = new Xe()), r.map = t, r.key = n), r.track();
	}
}
function nt(e, t, n, r, i, a) {
	let o = Qe.get(e);
	if (!o) {
		Je++;
		return;
	}
	let s = (e) => {
		e && e.trigger();
	};
	if (Fe(), t === "clear") o.forEach(s);
	else {
		let i = p(e), a = i && T(n);
		if (i && n === "length") {
			let e = Number(r);
			o.forEach((t, n) => {
				(n === "length" || n === tt || !y(n) && n >= e) && s(t);
			});
		} else switch ((n !== void 0 || o.has(void 0)) && s(o.get(n)), a && s(o.get(tt)), t) {
			case "add":
				i ? a && s(o.get("length")) : (s(o.get($e)), m(e) && s(o.get(et)));
				break;
			case "delete":
				i || (s(o.get($e)), m(e) && s(o.get(et)));
				break;
			case "set":
				m(e) && s(o.get($e));
				break;
		}
	}
	Ie();
}
function rt(e) {
	let t = /* @__PURE__ */ P(e);
	return t === e ? t : (N(t, "iterate", tt), /* @__PURE__ */ Ht(e) ? t : t.map(Gt));
}
function it(e) {
	return N(e = /* @__PURE__ */ P(e), "iterate", tt), e;
}
function at(e, t) {
	return /* @__PURE__ */ Vt(e) ? Kt(/* @__PURE__ */ Bt(e) ? Gt(t) : t) : Gt(t);
}
var ot = {
	__proto__: null,
	[Symbol.iterator]() {
		return st(this, Symbol.iterator, (e) => at(this, e));
	},
	concat(...e) {
		return rt(this).concat(...e.map((e) => p(e) ? rt(e) : e));
	},
	entries() {
		return st(this, "entries", (e) => (e[1] = at(this, e[1]), e));
	},
	every(e, t) {
		return lt(this, "every", e, t, void 0, arguments);
	},
	filter(e, t) {
		return lt(this, "filter", e, t, (e) => e.map((e) => at(this, e)), arguments);
	},
	find(e, t) {
		return lt(this, "find", e, t, (e) => at(this, e), arguments);
	},
	findIndex(e, t) {
		return lt(this, "findIndex", e, t, void 0, arguments);
	},
	findLast(e, t) {
		return lt(this, "findLast", e, t, (e) => at(this, e), arguments);
	},
	findLastIndex(e, t) {
		return lt(this, "findLastIndex", e, t, void 0, arguments);
	},
	forEach(e, t) {
		return lt(this, "forEach", e, t, void 0, arguments);
	},
	includes(...e) {
		return dt(this, "includes", e);
	},
	indexOf(...e) {
		return dt(this, "indexOf", e);
	},
	join(e) {
		return rt(this).join(e);
	},
	lastIndexOf(...e) {
		return dt(this, "lastIndexOf", e);
	},
	map(e, t) {
		return lt(this, "map", e, t, void 0, arguments);
	},
	pop() {
		return ft(this, "pop");
	},
	push(...e) {
		return ft(this, "push", e);
	},
	reduce(e, ...t) {
		return ut(this, "reduce", e, t);
	},
	reduceRight(e, ...t) {
		return ut(this, "reduceRight", e, t);
	},
	shift() {
		return ft(this, "shift");
	},
	some(e, t) {
		return lt(this, "some", e, t, void 0, arguments);
	},
	splice(...e) {
		return ft(this, "splice", e);
	},
	toReversed() {
		return rt(this).toReversed();
	},
	toSorted(e) {
		return rt(this).toSorted(e);
	},
	toSpliced(...e) {
		return rt(this).toSpliced(...e);
	},
	unshift(...e) {
		return ft(this, "unshift", e);
	},
	values() {
		return st(this, "values", (e) => at(this, e));
	}
};
function st(e, t, n) {
	let r = it(e), i = r[t]();
	return r !== e && !/* @__PURE__ */ Ht(e) && (i._next = i.next, i.next = () => {
		let e = i._next();
		return e.done || (e.value = n(e.value)), e;
	}), i;
}
var ct = Array.prototype;
function lt(e, t, n, r, i, a) {
	let o = it(e), s = o !== e && !/* @__PURE__ */ Ht(e), c = o[t];
	if (c !== ct[t]) {
		let t = c.apply(e, a);
		return s ? Gt(t) : t;
	}
	let l = n;
	o !== e && (s ? l = function(t, r) {
		return n.call(this, at(e, t), r, e);
	} : n.length > 2 && (l = function(t, r) {
		return n.call(this, t, r, e);
	}));
	let u = c.call(o, l, r);
	return s && i ? i(u) : u;
}
function ut(e, t, n, r) {
	let i = it(e), a = i !== e && !/* @__PURE__ */ Ht(e), o = n, s = !1;
	i !== e && (a ? (s = r.length === 0, o = function(t, r, i) {
		return s && (s = !1, t = at(e, t)), n.call(this, t, at(e, r), i, e);
	}) : n.length > 3 && (o = function(t, r, i) {
		return n.call(this, t, r, i, e);
	}));
	let c = i[t](o, ...r);
	return s ? at(e, c) : c;
}
function dt(e, t, n) {
	let r = /* @__PURE__ */ P(e);
	N(r, "iterate", tt);
	let i = r[t](...n);
	return (i === -1 || i === !1) && /* @__PURE__ */ Ut(n[0]) ? (n[0] = /* @__PURE__ */ P(n[0]), r[t](...n)) : i;
}
function ft(e, t, n = []) {
	Ge(), Fe();
	let r = (/* @__PURE__ */ P(e))[t].apply(e, n);
	return Ie(), Ke(), r;
}
var pt = /* @__PURE__ */ n("__proto__,__v_isRef,__isVue"), mt = new Set(/* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(y));
function ht(e) {
	y(e) || (e = String(e));
	let t = /* @__PURE__ */ P(this);
	return N(t, "has", e), t.hasOwnProperty(e);
}
var gt = class {
	constructor(e = !1, t = !1) {
		this._isReadonly = e, this._isShallow = t;
	}
	get(e, t, n) {
		if (t === "__v_skip") return e.__v_skip;
		let r = this._isReadonly, i = this._isShallow;
		if (t === "__v_isReactive") return !r;
		if (t === "__v_isReadonly") return r;
		if (t === "__v_isShallow") return i;
		if (t === "__v_raw") return n === (r ? i ? Pt : Nt : i ? Mt : jt).get(e) || Object.getPrototypeOf(e) === Object.getPrototypeOf(n) ? e : void 0;
		let a = p(e);
		if (!r) {
			let e;
			if (a && (e = ot[t])) return e;
			if (t === "hasOwnProperty") return ht;
		}
		let o = Reflect.get(e, t, /* @__PURE__ */ F(e) ? e : n);
		if ((y(t) ? mt.has(t) : pt(t)) || (r || N(e, "get", t), i)) return o;
		if (/* @__PURE__ */ F(o)) {
			let e = a && T(t) ? o : o.value;
			return r && b(e) ? /* @__PURE__ */ Rt(e) : e;
		}
		return b(o) ? r ? /* @__PURE__ */ Rt(o) : /* @__PURE__ */ It(o) : o;
	}
}, _t = class extends gt {
	constructor(e = !1) {
		super(!1, e);
	}
	set(e, t, n, r) {
		let i = e[t], a = p(e) && T(t);
		if (!this._isShallow) {
			let e = /* @__PURE__ */ Vt(i);
			if (!/* @__PURE__ */ Ht(n) && !/* @__PURE__ */ Vt(n) && (i = /* @__PURE__ */ P(i), n = /* @__PURE__ */ P(n)), !a && /* @__PURE__ */ F(i) && !/* @__PURE__ */ F(n)) return e || (i.value = n), !0;
		}
		let o = a ? Number(t) < e.length : f(e, t), s = Reflect.set(e, t, n, /* @__PURE__ */ F(e) ? e : r);
		return e === /* @__PURE__ */ P(r) && (o ? O(n, i) && nt(e, "set", t, n, i) : nt(e, "add", t, n)), s;
	}
	deleteProperty(e, t) {
		let n = f(e, t), r = e[t], i = Reflect.deleteProperty(e, t);
		return i && n && nt(e, "delete", t, void 0, r), i;
	}
	has(e, t) {
		let n = Reflect.has(e, t);
		return (!y(t) || !mt.has(t)) && N(e, "has", t), n;
	}
	ownKeys(e) {
		return N(e, "iterate", p(e) ? "length" : $e), Reflect.ownKeys(e);
	}
}, vt = class extends gt {
	constructor(e = !1) {
		super(!0, e);
	}
	set(e, t) {
		return !0;
	}
	deleteProperty(e, t) {
		return !0;
	}
}, yt = /* @__PURE__ */ new _t(), bt = /* @__PURE__ */ new vt(), xt = /* @__PURE__ */ new _t(!0), St = (e) => e, Ct = (e) => Reflect.getPrototypeOf(e);
function wt(e, t, n) {
	return function(...r) {
		let i = this.__v_raw, a = /* @__PURE__ */ P(i), o = m(a), s = e === "entries" || e === Symbol.iterator && o, c = e === "keys" && o, u = i[e](...r), d = n ? St : t ? Kt : Gt;
		return !t && N(a, "iterate", c ? et : $e), l(Object.create(u), { next() {
			let { value: e, done: t } = u.next();
			return t ? {
				value: e,
				done: t
			} : {
				value: s ? [d(e[0]), d(e[1])] : d(e),
				done: t
			};
		} });
	};
}
function Tt(e) {
	return function(...t) {
		return e === "delete" ? !1 : e === "clear" ? void 0 : this;
	};
}
function Et(e, t) {
	let n = {
		get(n) {
			let r = this.__v_raw, i = /* @__PURE__ */ P(r), a = /* @__PURE__ */ P(n);
			e || (O(n, a) && N(i, "get", n), N(i, "get", a));
			let { has: o } = Ct(i), s = t ? St : e ? Kt : Gt;
			if (o.call(i, n)) return s(r.get(n));
			if (o.call(i, a)) return s(r.get(a));
			r !== i && r.get(n);
		},
		get size() {
			let t = this.__v_raw;
			return !e && N(/* @__PURE__ */ P(t), "iterate", $e), t.size;
		},
		has(t) {
			let n = this.__v_raw, r = /* @__PURE__ */ P(n), i = /* @__PURE__ */ P(t);
			return e || (O(t, i) && N(r, "has", t), N(r, "has", i)), t === i ? n.has(t) : n.has(t) || n.has(i);
		},
		forEach(n, r) {
			let i = this, a = i.__v_raw, o = /* @__PURE__ */ P(a), s = t ? St : e ? Kt : Gt;
			return !e && N(o, "iterate", $e), a.forEach((e, t) => n.call(r, s(e), s(t), i));
		}
	};
	return l(n, e ? {
		add: Tt("add"),
		set: Tt("set"),
		delete: Tt("delete"),
		clear: Tt("clear")
	} : {
		add(e) {
			let n = /* @__PURE__ */ P(this), r = Ct(n), i = /* @__PURE__ */ P(e), a = !t && !/* @__PURE__ */ Ht(e) && !/* @__PURE__ */ Vt(e) ? i : e;
			return r.has.call(n, a) || O(e, a) && r.has.call(n, e) || O(i, a) && r.has.call(n, i) || (n.add(a), nt(n, "add", a, a)), this;
		},
		set(e, n) {
			!t && !/* @__PURE__ */ Ht(n) && !/* @__PURE__ */ Vt(n) && (n = /* @__PURE__ */ P(n));
			let r = /* @__PURE__ */ P(this), { has: i, get: a } = Ct(r), o = i.call(r, e);
			o ||= (e = /* @__PURE__ */ P(e), i.call(r, e));
			let s = a.call(r, e);
			return r.set(e, n), o ? O(n, s) && nt(r, "set", e, n, s) : nt(r, "add", e, n), this;
		},
		delete(e) {
			let t = /* @__PURE__ */ P(this), { has: n, get: r } = Ct(t), i = n.call(t, e);
			i ||= (e = /* @__PURE__ */ P(e), n.call(t, e));
			let a = r ? r.call(t, e) : void 0, o = t.delete(e);
			return i && nt(t, "delete", e, void 0, a), o;
		},
		clear() {
			let e = /* @__PURE__ */ P(this), t = e.size !== 0, n = e.clear();
			return t && nt(e, "clear", void 0, void 0, void 0), n;
		}
	}), [
		"keys",
		"values",
		"entries",
		Symbol.iterator
	].forEach((r) => {
		n[r] = wt(r, e, t);
	}), n;
}
function Dt(e, t) {
	let n = Et(e, t);
	return (t, r, i) => r === "__v_isReactive" ? !e : r === "__v_isReadonly" ? e : r === "__v_raw" ? t : Reflect.get(f(n, r) && r in t ? n : t, r, i);
}
var Ot = { get: /* @__PURE__ */ Dt(!1, !1) }, kt = { get: /* @__PURE__ */ Dt(!1, !0) }, At = { get: /* @__PURE__ */ Dt(!0, !1) }, jt = /* @__PURE__ */ new WeakMap(), Mt = /* @__PURE__ */ new WeakMap(), Nt = /* @__PURE__ */ new WeakMap(), Pt = /* @__PURE__ */ new WeakMap();
function Ft(e) {
	switch (e) {
		case "Object":
		case "Array": return 1;
		case "Map":
		case "Set":
		case "WeakMap":
		case "WeakSet": return 2;
		default: return 0;
	}
}
// @__NO_SIDE_EFFECTS__
function It(e) {
	return /* @__PURE__ */ Vt(e) ? e : zt(e, !1, yt, Ot, jt);
}
// @__NO_SIDE_EFFECTS__
function Lt(e) {
	return zt(e, !1, xt, kt, Mt);
}
// @__NO_SIDE_EFFECTS__
function Rt(e) {
	return zt(e, !0, bt, At, Nt);
}
function zt(e, t, n, r, i) {
	if (!b(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e)) return e;
	let a = i.get(e);
	if (a) return a;
	let o = Ft(w(e));
	if (o === 0) return e;
	let s = new Proxy(e, o === 2 ? r : n);
	return i.set(e, s), s;
}
// @__NO_SIDE_EFFECTS__
function Bt(e) {
	return /* @__PURE__ */ Vt(e) ? /* @__PURE__ */ Bt(e.__v_raw) : !!(e && e.__v_isReactive);
}
// @__NO_SIDE_EFFECTS__
function Vt(e) {
	return !!(e && e.__v_isReadonly);
}
// @__NO_SIDE_EFFECTS__
function Ht(e) {
	return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function Ut(e) {
	return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function P(e) {
	let t = e && e.__v_raw;
	return t ? /* @__PURE__ */ P(t) : e;
}
function Wt(e) {
	return !f(e, "__v_skip") && Object.isExtensible(e) && ce(e, "__v_skip", !0), e;
}
var Gt = (e) => b(e) ? /* @__PURE__ */ It(e) : e, Kt = (e) => b(e) ? /* @__PURE__ */ Rt(e) : e;
// @__NO_SIDE_EFFECTS__
function F(e) {
	return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function I(e) {
	return Jt(e, !1);
}
// @__NO_SIDE_EFFECTS__
function qt(e) {
	return Jt(e, !0);
}
function Jt(e, t) {
	return /* @__PURE__ */ F(e) ? e : new Yt(e, t);
}
var Yt = class {
	constructor(e, t) {
		this.dep = new Xe(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = t ? e : /* @__PURE__ */ P(e), this._value = t ? e : Gt(e), this.__v_isShallow = t;
	}
	get value() {
		return this.dep.track(), this._value;
	}
	set value(e) {
		let t = this._rawValue, n = this.__v_isShallow || /* @__PURE__ */ Ht(e) || /* @__PURE__ */ Vt(e);
		e = n ? e : /* @__PURE__ */ P(e), O(e, t) && (this._rawValue = e, this._value = n ? e : Gt(e), this.dep.trigger());
	}
};
function L(e) {
	return /* @__PURE__ */ F(e) ? e.value : e;
}
var Xt = {
	get: (e, t, n) => t === "__v_raw" ? e : L(Reflect.get(e, t, n)),
	set: (e, t, n, r) => {
		let i = e[t];
		return /* @__PURE__ */ F(i) && !/* @__PURE__ */ F(n) ? (i.value = n, !0) : Reflect.set(e, t, n, r);
	}
};
function Zt(e) {
	return /* @__PURE__ */ Bt(e) ? e : new Proxy(e, Xt);
}
var Qt = class {
	constructor(e) {
		this.__v_isRef = !0, this._value = void 0;
		let t = this.dep = new Xe(), { get: n, set: r } = e(t.track.bind(t), t.trigger.bind(t));
		this._get = n, this._set = r;
	}
	get value() {
		return this._value = this._get();
	}
	set value(e) {
		this._set(e);
	}
};
function $t(e) {
	return new Qt(e);
}
var en = class {
	constructor(e, t, n) {
		this.fn = e, this.setter = t, this._value = void 0, this.dep = new Xe(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = Je - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !t, this.isSSR = n;
	}
	notify() {
		if (this.flags |= 16, !(this.flags & 8) && M !== this) return Pe(this, !0), !0;
	}
	get value() {
		let e = this.dep.track();
		return Be(this), e && (e.version = this.dep.version), this._value;
	}
	set value(e) {
		this.setter && this.setter(e);
	}
};
// @__NO_SIDE_EFFECTS__
function tn(e, t, n = !1) {
	let r, i;
	return _(e) ? r = e : (r = e.get, i = e.set), new en(r, i, n);
}
var nn = {}, rn = /* @__PURE__ */ new WeakMap(), an = void 0;
function on(e, t = !1, n = an) {
	if (n) {
		let t = rn.get(n);
		t || rn.set(n, t = []), t.push(e);
	}
}
function sn(e, t, n = r) {
	let { immediate: i, deep: o, once: s, scheduler: c, augmentJob: l, call: d } = n, f = (e) => o ? e : /* @__PURE__ */ Ht(e) || o === !1 || o === 0 ? cn(e, 1) : cn(e), m, h, g, v, y = !1, b = !1;
	if (/* @__PURE__ */ F(e) ? (h = () => e.value, y = /* @__PURE__ */ Ht(e)) : /* @__PURE__ */ Bt(e) ? (h = () => f(e), y = !0) : p(e) ? (b = !0, y = e.some((e) => /* @__PURE__ */ Bt(e) || /* @__PURE__ */ Ht(e)), h = () => e.map((e) => {
		if (/* @__PURE__ */ F(e)) return e.value;
		if (/* @__PURE__ */ Bt(e)) return f(e);
		if (_(e)) return d ? d(e, 2) : e();
	})) : h = _(e) ? t ? d ? () => d(e, 2) : e : () => {
		if (g) {
			Ge();
			try {
				g();
			} finally {
				Ke();
			}
		}
		let t = an;
		an = m;
		try {
			return d ? d(e, 3, [v]) : e(v);
		} finally {
			an = t;
		}
	} : a, t && o) {
		let e = h, t = o === !0 ? Infinity : o;
		h = () => cn(e(), t);
	}
	let x = Oe(), S = () => {
		m.stop(), x && x.active && u(x.effects, m);
	};
	if (s && t) {
		let e = t;
		t = (...t) => {
			let n = e(...t);
			return S(), n;
		};
	}
	let C = b ? Array(e.length).fill(nn) : nn, w = (e) => {
		if (!(!(m.flags & 1) || !m.dirty && !e)) if (t) {
			let n = m.run();
			if (e || o || y || (b ? n.some((e, t) => O(e, C[t])) : O(n, C))) {
				g && g();
				let e = an;
				an = m;
				try {
					let e = [
						n,
						C === nn ? void 0 : b && C[0] === nn ? [] : C,
						v
					];
					C = n, d ? d(t, 3, e) : t(...e);
				} finally {
					an = e;
				}
			}
		} else m.run();
	};
	return l && l(w), m = new Ae(h), m.scheduler = c ? () => c(w, !1) : w, v = (e) => on(e, !1, m), g = m.onStop = () => {
		let e = rn.get(m);
		if (e) {
			if (d) d(e, 4);
			else for (let t of e) t();
			rn.delete(m);
		}
	}, t ? i ? w(!0) : C = m.run() : c ? c(w.bind(null, !0), !0) : m.run(), S.pause = m.pause.bind(m), S.resume = m.resume.bind(m), S.stop = S, S;
}
function cn(e, t = Infinity, n) {
	if (t <= 0 || !b(e) || e.__v_skip || (n ||= /* @__PURE__ */ new Map(), (n.get(e) || 0) >= t)) return e;
	if (n.set(e, t), t--, /* @__PURE__ */ F(e)) cn(e.value, t, n);
	else if (p(e)) for (let r = 0; r < e.length; r++) cn(e[r], t, n);
	else if (h(e) || m(e)) e.forEach((e) => {
		cn(e, t, n);
	});
	else if (ee(e)) {
		for (let r in e) cn(e[r], t, n);
		for (let r of Object.getOwnPropertySymbols(e)) Object.prototype.propertyIsEnumerable.call(e, r) && cn(e[r], t, n);
	}
	return e;
}
//#endregion
//#region node_modules/@vue/runtime-core/dist/runtime-core.esm-bundler.js
function ln(e, t, n, r) {
	try {
		return r ? e(...r) : e();
	} catch (e) {
		dn(e, t, n);
	}
}
function un(e, t, n, r) {
	if (_(e)) {
		let i = ln(e, t, n, r);
		return i && x(i) && i.catch((e) => {
			dn(e, t, n);
		}), i;
	}
	if (p(e)) {
		let i = [];
		for (let a = 0; a < e.length; a++) i.push(un(e[a], t, n, r));
		return i;
	}
}
function dn(e, t, n, i = !0) {
	let a = t ? t.vnode : null, { errorHandler: o, throwUnhandledErrorInProduction: s } = t && t.appContext.config || r;
	if (t) {
		let r = t.parent, i = t.proxy, a = `https://vuejs.org/error-reference/#runtime-${n}`;
		for (; r;) {
			let t = r.ec;
			if (t) {
				for (let n = 0; n < t.length; n++) if (t[n](e, i, a) === !1) return;
			}
			r = r.parent;
		}
		if (o) {
			Ge(), ln(o, null, 10, [
				e,
				i,
				a
			]), Ke();
			return;
		}
	}
	fn(e, n, a, i, s);
}
function fn(e, t, n, r = !0, i = !1) {
	if (i) throw e;
	console.error(e);
}
var pn = [], mn = -1, hn = [], gn = null, _n = 0, vn = /* @__PURE__ */ Promise.resolve(), yn = null;
function bn(e) {
	let t = yn || vn;
	return e ? t.then(this ? e.bind(this) : e) : t;
}
function xn(e) {
	let t = mn + 1, n = pn.length;
	for (; t < n;) {
		let r = t + n >>> 1, i = pn[r], a = Dn(i);
		a < e || a === e && i.flags & 2 ? t = r + 1 : n = r;
	}
	return t;
}
function Sn(e) {
	if (!(e.flags & 1)) {
		let t = Dn(e), n = pn[pn.length - 1];
		!n || !(e.flags & 2) && t >= Dn(n) ? pn.push(e) : pn.splice(xn(t), 0, e), e.flags |= 1, Cn();
	}
}
function Cn() {
	yn ||= vn.then(On);
}
function wn(e) {
	p(e) ? hn.push(...e) : gn && e.id === -1 ? gn.splice(_n + 1, 0, e) : e.flags & 1 || (hn.push(e), e.flags |= 1), Cn();
}
function Tn(e, t, n = mn + 1) {
	for (; n < pn.length; n++) {
		let t = pn[n];
		if (t && t.flags & 2) {
			if (e && t.id !== e.uid) continue;
			pn.splice(n, 1), n--, t.flags & 4 && (t.flags &= -2), t(), t.flags & 4 || (t.flags &= -2);
		}
	}
}
function En(e) {
	if (hn.length) {
		let e = [...new Set(hn)].sort((e, t) => Dn(e) - Dn(t));
		if (hn.length = 0, gn) {
			gn.push(...e);
			return;
		}
		for (gn = e, _n = 0; _n < gn.length; _n++) {
			let e = gn[_n];
			e.flags & 4 && (e.flags &= -2), e.flags & 8 || e(), e.flags &= -2;
		}
		gn = null, _n = 0;
	}
}
var Dn = (e) => e.id == null ? e.flags & 2 ? -1 : Infinity : e.id;
function On(e) {
	try {
		for (mn = 0; mn < pn.length; mn++) {
			let e = pn[mn];
			e && !(e.flags & 8) && (e.flags & 4 && (e.flags &= -2), ln(e, e.i, e.i ? 15 : 14), e.flags & 4 || (e.flags &= -2));
		}
	} finally {
		for (; mn < pn.length; mn++) {
			let e = pn[mn];
			e && (e.flags &= -2);
		}
		mn = -1, pn.length = 0, En(e), yn = null, (pn.length || hn.length) && On(e);
	}
}
var R = null, kn = null;
function An(e) {
	let t = R;
	return R = e, kn = e && e.type.__scopeId || null, t;
}
function jn(e, t = R, n) {
	if (!t || e._n) return e;
	let r = (...n) => {
		r._d && ga(-1);
		let i = An(t), a;
		try {
			a = e(...n);
		} finally {
			An(i), r._d && ga(1);
		}
		return a;
	};
	return r._n = !0, r._c = !0, r._d = !0, r;
}
function z(e, t) {
	if (R === null) return e;
	let n = Ja(R), i = e.dirs ||= [];
	for (let e = 0; e < t.length; e++) {
		let [a, o, s, c = r] = t[e];
		a && (_(a) && (a = {
			mounted: a,
			updated: a
		}), a.deep && cn(o), i.push({
			dir: a,
			instance: n,
			value: o,
			oldValue: void 0,
			arg: s,
			modifiers: c
		}));
	}
	return e;
}
function Mn(e, t, n, r) {
	let i = e.dirs, a = t && t.dirs;
	for (let o = 0; o < i.length; o++) {
		let s = i[o];
		a && (s.oldValue = a[o].value);
		let c = s.dir[r];
		c && (Ge(), un(c, n, 8, [
			e.el,
			s,
			e,
			t
		]), Ke());
	}
}
function Nn(e, t) {
	if (X) {
		let n = X.provides, r = X.parent && X.parent.provides;
		r === n && (n = X.provides = Object.create(r)), n[e] = t;
	}
}
function Pn(e, t, n = !1) {
	let r = Na();
	if (r || yi) {
		let i = yi ? yi._context.provides : r ? r.parent == null || r.ce ? r.vnode.appContext && r.vnode.appContext.provides : r.parent.provides : void 0;
		if (i && e in i) return i[e];
		if (arguments.length > 1) return n && _(t) ? t.call(r && r.proxy) : t;
	}
}
var Fn = /* @__PURE__ */ Symbol.for("v-scx"), In = () => Pn(Fn);
function Ln(e, t) {
	return zn(e, null, { flush: "sync" });
}
function Rn(e, t, n) {
	return zn(e, t, n);
}
function zn(e, t, n = r) {
	let { immediate: i, deep: o, flush: s, once: c } = n, u = l({}, n), d = t && i || !t && s !== "post", f;
	if (za) {
		if (s === "sync") {
			let e = In();
			f = e.__watcherHandles ||= [];
		} else if (!d) {
			let e = () => {};
			return e.stop = a, e.resume = a, e.pause = a, e;
		}
	}
	let p = X;
	u.call = (e, t, n) => un(e, p, t, n);
	let m = !1;
	s === "post" ? u.scheduler = (e) => {
		Zi(e, p && p.suspense);
	} : s !== "sync" && (m = !0, u.scheduler = (e, t) => {
		t ? e() : Sn(e);
	}), u.augmentJob = (e) => {
		t && (e.flags |= 4), m && (e.flags |= 2, p && (e.id = p.uid, e.i = p));
	};
	let h = sn(e, t, u);
	return za && (f ? f.push(h) : d && h()), h;
}
function Bn(e, t, n) {
	let r = this.proxy, i = v(e) ? e.includes(".") ? Vn(r, e) : () => r[e] : e.bind(r, r), a;
	_(t) ? a = t : (a = t.handler, n = t);
	let o = Ia(this), s = zn(i, a.bind(r), n);
	return o(), s;
}
function Vn(e, t) {
	let n = t.split(".");
	return () => {
		let t = e;
		for (let e = 0; e < n.length && t; e++) t = t[n[e]];
		return t;
	};
}
var Hn = /* @__PURE__ */ new WeakMap(), Un = /* @__PURE__ */ Symbol("_vte"), Wn = (e) => e.__isTeleport, Gn = (e) => e && (e.disabled || e.disabled === ""), Kn = (e) => e && (e.defer || e.defer === ""), qn = (e) => typeof SVGElement < "u" && e instanceof SVGElement, Jn = (e) => typeof MathMLElement == "function" && e instanceof MathMLElement, Yn = (e, t) => {
	let n = e && e.to;
	return v(n) ? t ? t(n) : null : n;
}, Xn = {
	name: "Teleport",
	__isTeleport: !0,
	process(e, t, n, r, i, a, o, s, c, l) {
		let { mc: u, pc: d, pbc: f, o: { insert: p, querySelector: m, createText: h, createComment: g, parentNode: _ } } = l, v = Gn(t.props), { dynamicChildren: y } = t, b = (e, t, n) => {
			e.shapeFlag & 16 && u(e.children, t, n, i, a, o, s, c);
		}, x = (e = t) => {
			let n = Gn(e.props), r = e.target = Yn(e.props, m), a = tr(r, e, h, p);
			r && (o !== "svg" && qn(r) ? o = "svg" : o !== "mathml" && Jn(r) && (o = "mathml"), i && i.isCE && (i.ce._teleportTargets || (i.ce._teleportTargets = /* @__PURE__ */ new Set())).add(r), n || (b(e, r, a), er(e, !1)));
		}, S = (e) => {
			let t = () => {
				Hn.get(e) === t && (Hn.delete(e), Gn(e.props) && (b(e, _(e.el) || n, e.anchor), er(e, !0)), x(e));
			};
			Hn.set(e, t), Zi(t, a);
		};
		if (e == null) {
			let e = t.el = h(""), i = t.anchor = h("");
			if (p(e, n, r), p(i, n, r), Kn(t.props) || a && a.pendingBranch) {
				S(t);
				return;
			}
			v && (b(t, n, i), er(t, !0)), x();
		} else {
			t.el = e.el;
			let r = t.anchor = e.anchor, u = Hn.get(e);
			if (u) {
				u.flags |= 8, Hn.delete(e), S(t);
				return;
			}
			t.targetStart = e.targetStart;
			let p = t.target = e.target, h = t.targetAnchor = e.targetAnchor, g = Gn(e.props), _ = g ? n : p, b = g ? r : h;
			if (o === "svg" || qn(p) ? o = "svg" : (o === "mathml" || Jn(p)) && (o = "mathml"), y ? (f(e.dynamicChildren, y, _, i, a, o, s), ra(e, t, !0)) : c || d(e, t, _, b, i, a, o, s, !1), v) g ? t.props && e.props && t.props.to !== e.props.to && (t.props.to = e.props.to) : Zn(t, n, r, l, 1);
			else if ((t.props && t.props.to) !== (e.props && e.props.to)) {
				let e = t.target = Yn(t.props, m);
				e && Zn(t, e, null, l, 0);
			} else g && Zn(t, p, h, l, 1);
			er(t, v);
		}
	},
	remove(e, t, n, { um: r, o: { remove: i } }, a) {
		let { shapeFlag: o, children: s, anchor: c, targetStart: l, targetAnchor: u, target: d, props: f } = e, p = a || !Gn(f), m = Hn.get(e);
		if (m && (m.flags |= 8, Hn.delete(e)), d && (i(l), i(u)), a && i(c), !m && o & 16) for (let e = 0; e < s.length; e++) {
			let i = s[e];
			r(i, t, n, p, !!i.dynamicChildren);
		}
	},
	move: Zn,
	hydrate: Qn
};
function Zn(e, t, n, { o: { insert: r }, m: i }, a = 2) {
	a === 0 && r(e.targetAnchor, t, n);
	let { el: o, anchor: s, shapeFlag: c, children: l, props: u } = e, d = a === 2;
	if (d && r(o, t, n), !Hn.has(e) && (!d || Gn(u)) && c & 16) for (let e = 0; e < l.length; e++) i(l[e], t, n, 2);
	d && r(s, t, n);
}
function Qn(e, t, n, r, i, a, { o: { nextSibling: o, parentNode: s, querySelector: c, insert: l, createText: u } }, d) {
	function f(e, n) {
		let r = n;
		for (; r;) {
			if (r && r.nodeType === 8) {
				if (r.data === "teleport start anchor") t.targetStart = r;
				else if (r.data === "teleport anchor") {
					t.targetAnchor = r, e._lpa = t.targetAnchor && o(t.targetAnchor);
					break;
				}
			}
			r = o(r);
		}
	}
	function p(e, t) {
		t.anchor = d(o(e), t, s(e), n, r, i, a);
	}
	let m = t.target = Yn(t.props, c), h = Gn(t.props);
	if (m) {
		let c = m._lpa || m.firstChild;
		t.shapeFlag & 16 && (h ? (p(e, t), f(m, c), t.targetAnchor || tr(m, t, u, l, s(e) === m ? e : null)) : (t.anchor = o(e), f(m, c), t.targetAnchor || tr(m, t, u, l), d(c && o(c), t, m, n, r, i, a))), er(t, h);
	} else h && t.shapeFlag & 16 && (p(e, t), t.targetStart = e, t.targetAnchor = o(e));
	return t.anchor && o(t.anchor);
}
var $n = Xn;
function er(e, t) {
	let n = e.ctx;
	if (n && n.ut) {
		let r, i;
		for (t ? (r = e.el, i = e.anchor) : (r = e.targetStart, i = e.targetAnchor); r && r !== i;) r.nodeType === 1 && r.setAttribute("data-v-owner", n.uid), r = r.nextSibling;
		n.ut();
	}
}
function tr(e, t, n, r, i = null) {
	let a = t.targetStart = n(""), o = t.targetAnchor = n("");
	return a[Un] = o, e && (r(a, e, i), r(o, e, i)), o;
}
var nr = /* @__PURE__ */ Symbol("_leaveCb"), rr = /* @__PURE__ */ Symbol("_enterCb");
function ir() {
	let e = {
		isMounted: !1,
		isLeaving: !1,
		isUnmounting: !1,
		leavingVNodes: /* @__PURE__ */ new Map()
	};
	return Nr(() => {
		e.isMounted = !0;
	}), Ir(() => {
		e.isUnmounting = !0;
	}), e;
}
var ar = [Function, Array], or = {
	mode: String,
	appear: Boolean,
	persisted: Boolean,
	onBeforeEnter: ar,
	onEnter: ar,
	onAfterEnter: ar,
	onEnterCancelled: ar,
	onBeforeLeave: ar,
	onLeave: ar,
	onAfterLeave: ar,
	onLeaveCancelled: ar,
	onBeforeAppear: ar,
	onAppear: ar,
	onAfterAppear: ar,
	onAppearCancelled: ar
}, sr = (e) => {
	let t = e.subTree;
	return t.component ? sr(t.component) : t;
}, cr = {
	name: "BaseTransition",
	props: or,
	setup(e, { slots: t }) {
		let n = Na(), r = ir();
		return () => {
			let i = t.default && gr(t.default(), !0), a = i && i.length ? lr(i) : n.subTree ? Y() : void 0;
			if (!a) return;
			let o = /* @__PURE__ */ P(e), { mode: s } = o;
			if (r.isLeaving) return pr(a);
			let c = mr(a);
			if (!c) return pr(a);
			let l = fr(c, o, r, n, (e) => l = e);
			c.type !== H && hr(c, l);
			let u = n.subTree && mr(n.subTree);
			if (u && u.type !== H && !ya(u, c) && sr(n).type !== H) {
				let e = fr(u, o, r, n);
				if (hr(u, e), s === "out-in" && c.type !== H) return r.isLeaving = !0, e.afterLeave = () => {
					r.isLeaving = !1, n.job.flags & 8 || n.update(), delete e.afterLeave, u = void 0;
				}, pr(a);
				s === "in-out" && c.type !== H ? e.delayLeave = (e, t, n) => {
					let i = dr(r, u);
					i[String(u.key)] = u, e[nr] = () => {
						t(), e[nr] = void 0, delete l.delayedLeave, u = void 0;
					}, l.delayedLeave = () => {
						n(), delete l.delayedLeave, u = void 0;
					};
				} : u = void 0;
			} else u &&= void 0;
			return a;
		};
	}
};
function lr(e) {
	let t = e[0];
	if (e.length > 1) {
		for (let n of e) if (n.type !== H) {
			t = n;
			break;
		}
	}
	return t;
}
var ur = cr;
function dr(e, t) {
	let { leavingVNodes: n } = e, r = n.get(t.type);
	return r || (r = /* @__PURE__ */ Object.create(null), n.set(t.type, r)), r;
}
function fr(e, t, n, r, i) {
	let { appear: a, mode: o, persisted: s = !1, onBeforeEnter: c, onEnter: l, onAfterEnter: u, onEnterCancelled: d, onBeforeLeave: f, onLeave: m, onAfterLeave: h, onLeaveCancelled: g, onBeforeAppear: _, onAppear: v, onAfterAppear: y, onAppearCancelled: b } = t, x = String(e.key), S = dr(n, e), C = (e, t) => {
		e && un(e, r, 9, t);
	}, w = (e, t) => {
		let n = t[1];
		C(e, t), p(e) ? e.every((e) => e.length <= 1) && n() : e.length <= 1 && n();
	}, ee = {
		mode: o,
		persisted: s,
		beforeEnter(t) {
			let r = c;
			if (!n.isMounted) if (a) r = _ || c;
			else return;
			t[nr] && t[nr](!0);
			let i = S[x];
			i && ya(e, i) && i.el[nr] && i.el[nr](), C(r, [t]);
		},
		enter(t) {
			if (S[x] === e) return;
			let r = l, i = u, o = d;
			if (!n.isMounted) if (a) r = v || l, i = y || u, o = b || d;
			else return;
			let s = !1;
			t[rr] = (e) => {
				s || (s = !0, C(e ? o : i, [t]), ee.delayedLeave && ee.delayedLeave(), t[rr] = void 0);
			};
			let c = t[rr].bind(null, !1);
			r ? w(r, [t, c]) : c();
		},
		leave(t, r) {
			let i = String(e.key);
			if (t[rr] && t[rr](!0), n.isUnmounting) return r();
			C(f, [t]);
			let a = !1;
			t[nr] = (n) => {
				a || (a = !0, r(), C(n ? g : h, [t]), t[nr] = void 0, S[i] === e && delete S[i]);
			};
			let o = t[nr].bind(null, !1);
			S[i] = e, m ? w(m, [t, o]) : o();
		},
		clone(e) {
			let a = fr(e, t, n, r, i);
			return i && i(a), a;
		}
	};
	return ee;
}
function pr(e) {
	if (Tr(e)) return e = wa(e), e.children = null, e;
}
function mr(e) {
	if (!Tr(e)) return Wn(e.type) && e.children ? lr(e.children) : e;
	if (e.component) return e.component.subTree;
	let { shapeFlag: t, children: n } = e;
	if (n) {
		if (t & 16) return n[0];
		if (t & 32 && _(n.default)) return n.default();
	}
}
function hr(e, t) {
	e.shapeFlag & 6 && e.component ? (e.transition = t, hr(e.component.subTree, t)) : e.shapeFlag & 128 ? (e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback)) : e.transition = t;
}
function gr(e, t = !1, n) {
	let r = [], i = 0;
	for (let a = 0; a < e.length; a++) {
		let o = e[a], s = n == null ? o.key : String(n) + String(o.key == null ? a : o.key);
		o.type === V ? (o.patchFlag & 128 && i++, r = r.concat(gr(o.children, t, s))) : (t || o.type !== H) && r.push(s == null ? o : wa(o, { key: s }));
	}
	if (i > 1) for (let e = 0; e < r.length; e++) r[e].patchFlag = -2;
	return r;
}
// @__NO_SIDE_EFFECTS__
function _r(e, t) {
	return _(e) ? /* @__PURE__ */ l({ name: e.name }, t, { setup: e }) : e;
}
function vr() {
	let e = Na();
	return e ? (e.appContext.config.idPrefix || "v") + "-" + e.ids[0] + e.ids[1]++ : "";
}
function yr(e) {
	e.ids = [
		e.ids[0] + e.ids[2]++ + "-",
		0,
		0
	];
}
function br(e, t) {
	let n;
	return !!((n = Object.getOwnPropertyDescriptor(e, t)) && !n.configurable);
}
var xr = /* @__PURE__ */ new WeakMap();
function Sr(e, t, n, i, a = !1) {
	if (p(e)) {
		e.forEach((e, r) => Sr(e, t && (p(t) ? t[r] : t), n, i, a));
		return;
	}
	if (wr(i) && !a) {
		i.shapeFlag & 512 && i.type.__asyncResolved && i.component.subTree.component && Sr(e, t, n, i.component.subTree);
		return;
	}
	let s = i.shapeFlag & 4 ? Ja(i.component) : i.el, c = a ? null : s, { i: l, r: d } = e, m = t && t.r, h = l.refs === r ? l.refs = {} : l.refs, g = l.setupState, y = /* @__PURE__ */ P(g), b = g === r ? o : (e) => br(h, e) ? !1 : f(y, e), x = (e, t) => !(t && br(h, t));
	if (m != null && m !== d) {
		if (Cr(t), v(m)) h[m] = null, b(m) && (g[m] = null);
		else if (/* @__PURE__ */ F(m)) {
			let e = t;
			x(m, e.k) && (m.value = null), e.k && (h[e.k] = null);
		}
	}
	if (_(d)) ln(d, l, 12, [c, h]);
	else {
		let t = v(d), r = /* @__PURE__ */ F(d);
		if (t || r) {
			let i = () => {
				if (e.f) {
					let n = t ? b(d) ? g[d] : h[d] : x(d) || !e.k ? d.value : h[e.k];
					if (a) p(n) && u(n, s);
					else if (p(n)) n.includes(s) || n.push(s);
					else if (t) h[d] = [s], b(d) && (g[d] = h[d]);
					else {
						let t = [s];
						x(d, e.k) && (d.value = t), e.k && (h[e.k] = t);
					}
				} else t ? (h[d] = c, b(d) && (g[d] = c)) : r && (x(d, e.k) && (d.value = c), e.k && (h[e.k] = c));
			};
			if (c) {
				let t = () => {
					i(), xr.delete(e);
				};
				t.id = -1, xr.set(e, t), Zi(t, n);
			} else Cr(e), i();
		}
	}
}
function Cr(e) {
	let t = xr.get(e);
	t && (t.flags |= 8, xr.delete(e));
}
fe().requestIdleCallback, fe().cancelIdleCallback;
var wr = (e) => !!e.type.__asyncLoader, Tr = (e) => e.type.__isKeepAlive;
function Er(e, t) {
	Or(e, "a", t);
}
function Dr(e, t) {
	Or(e, "da", t);
}
function Or(e, t, n = X) {
	let r = e.__wdc ||= () => {
		let t = n;
		for (; t;) {
			if (t.isDeactivated) return;
			t = t.parent;
		}
		return e();
	};
	if (Ar(t, r, n), n) {
		let e = n.parent;
		for (; e && e.parent;) Tr(e.parent.vnode) && kr(r, t, n, e), e = e.parent;
	}
}
function kr(e, t, n, r) {
	let i = Ar(t, e, r, !0);
	Lr(() => {
		u(r[t], i);
	}, n);
}
function Ar(e, t, n = X, r = !1) {
	if (n) {
		let i = n[e] || (n[e] = []), a = t.__weh ||= (...r) => {
			Ge();
			let i = Ia(n), a = un(t, n, e, r);
			return i(), Ke(), a;
		};
		return r ? i.unshift(a) : i.push(a), a;
	}
}
var jr = (e) => (t, n = X) => {
	(!za || e === "sp") && Ar(e, (...e) => t(...e), n);
}, Mr = jr("bm"), Nr = jr("m"), Pr = jr("bu"), Fr = jr("u"), Ir = jr("bum"), Lr = jr("um"), Rr = jr("sp"), zr = jr("rtg"), Br = jr("rtc");
function Vr(e, t = X) {
	Ar("ec", e, t);
}
var Hr = "components", Ur = /* @__PURE__ */ Symbol.for("v-ndc");
function Wr(e) {
	return v(e) ? Gr(Hr, e, !1) || e : e || Ur;
}
function Gr(e, t, n = !0, r = !1) {
	let i = R || X;
	if (i) {
		let n = i.type;
		if (e === Hr) {
			let e = Ya(n, !1);
			if (e && (e === t || e === D(t) || e === ae(D(t)))) return n;
		}
		let a = Kr(i[e] || n[e], t) || Kr(i.appContext[e], t);
		return !a && r ? n : a;
	}
}
function Kr(e, t) {
	return e && (e[t] || e[D(t)] || e[ae(D(t))]);
}
function B(e, t, n, r) {
	let i, a = n && n[r], o = p(e);
	if (o || v(e)) {
		let n = o && /* @__PURE__ */ Bt(e), r = !1, s = !1;
		n && (r = !/* @__PURE__ */ Ht(e), s = /* @__PURE__ */ Vt(e), e = it(e)), i = Array(e.length);
		for (let n = 0, o = e.length; n < o; n++) i[n] = t(r ? s ? Kt(Gt(e[n])) : Gt(e[n]) : e[n], n, void 0, a && a[n]);
	} else if (typeof e == "number") {
		i = Array(e);
		for (let n = 0; n < e; n++) i[n] = t(n + 1, n, void 0, a && a[n]);
	} else if (b(e)) if (e[Symbol.iterator]) i = Array.from(e, (e, n) => t(e, n, void 0, a && a[n]));
	else {
		let n = Object.keys(e);
		i = Array(n.length);
		for (let r = 0, o = n.length; r < o; r++) {
			let o = n[r];
			i[r] = t(e[o], o, r, a && a[r]);
		}
	}
	else i = [];
	return n && (n[r] = i), i;
}
function qr(e, t, n = {}, r, i) {
	if (R.ce || R.parent && wr(R.parent) && R.parent.ce) {
		let e = Object.keys(n).length > 0;
		return t !== "default" && (n.name = t), U(), G(V, null, [q("slot", n, r && r())], e ? -2 : 64);
	}
	let a = e[t];
	a && a._c && (a._d = !1), U();
	let o = a && Jr(a(n)), s = n.key || o && o.key, c = G(V, { key: (s && !y(s) ? s : `_${t}`) + (!o && r ? "_fb" : "") }, o || (r ? r() : []), o && e._ === 1 ? 64 : -2);
	return !i && c.scopeId && (c.slotScopeIds = [c.scopeId + "-s"]), a && a._c && (a._d = !0), c;
}
function Jr(e) {
	return e.some((e) => va(e) ? !(e.type === H || e.type === V && !Jr(e.children)) : !0) ? e : null;
}
var Yr = (e) => e ? Ra(e) ? Ja(e) : Yr(e.parent) : null, Xr = /* @__PURE__ */ l(/* @__PURE__ */ Object.create(null), {
	$: (e) => e,
	$el: (e) => e.vnode.el,
	$data: (e) => e.data,
	$props: (e) => e.props,
	$attrs: (e) => e.attrs,
	$slots: (e) => e.slots,
	$refs: (e) => e.refs,
	$parent: (e) => Yr(e.parent),
	$root: (e) => Yr(e.root),
	$host: (e) => e.ce,
	$emit: (e) => e.emit,
	$options: (e) => oi(e),
	$forceUpdate: (e) => e.f ||= () => {
		Sn(e.update);
	},
	$nextTick: (e) => e.n ||= bn.bind(e.proxy),
	$watch: (e) => Bn.bind(e)
}), Zr = (e, t) => e !== r && !e.__isScriptSetup && f(e, t), Qr = {
	get({ _: e }, t) {
		if (t === "__v_skip") return !0;
		let { ctx: n, setupState: i, data: a, props: o, accessCache: s, type: c, appContext: l } = e;
		if (t[0] !== "$") {
			let e = s[t];
			if (e !== void 0) switch (e) {
				case 1: return i[t];
				case 2: return a[t];
				case 4: return n[t];
				case 3: return o[t];
			}
			else if (Zr(i, t)) return s[t] = 1, i[t];
			else if (a !== r && f(a, t)) return s[t] = 2, a[t];
			else if (f(o, t)) return s[t] = 3, o[t];
			else if (n !== r && f(n, t)) return s[t] = 4, n[t];
			else ti && (s[t] = 0);
		}
		let u = Xr[t], d, p;
		if (u) return t === "$attrs" && N(e.attrs, "get", ""), u(e);
		if ((d = c.__cssModules) && (d = d[t])) return d;
		if (n !== r && f(n, t)) return s[t] = 4, n[t];
		if (p = l.config.globalProperties, f(p, t)) return p[t];
	},
	set({ _: e }, t, n) {
		let { data: i, setupState: a, ctx: o } = e;
		return Zr(a, t) ? (a[t] = n, !0) : i !== r && f(i, t) ? (i[t] = n, !0) : f(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (o[t] = n, !0);
	},
	has({ _: { data: e, setupState: t, accessCache: n, ctx: i, appContext: a, props: o, type: s } }, c) {
		let l;
		return !!(n[c] || e !== r && c[0] !== "$" && f(e, c) || Zr(t, c) || f(o, c) || f(i, c) || f(Xr, c) || f(a.config.globalProperties, c) || (l = s.__cssModules) && l[c]);
	},
	defineProperty(e, t, n) {
		return n.get == null ? f(n, "value") && this.set(e, t, n.value, null) : e._.accessCache[t] = 0, Reflect.defineProperty(e, t, n);
	}
};
function $r(e) {
	return p(e) ? e.reduce((e, t) => (e[t] = null, e), {}) : e;
}
function ei(e, t) {
	return !e || !t ? e || t : p(e) && p(t) ? e.concat(t) : l({}, $r(e), $r(t));
}
var ti = !0;
function ni(e) {
	let t = oi(e), n = e.proxy, r = e.ctx;
	ti = !1, t.beforeCreate && ii(t.beforeCreate, e, "bc");
	let { data: i, computed: o, methods: s, watch: c, provide: l, inject: u, created: d, beforeMount: f, mounted: m, beforeUpdate: h, updated: g, activated: v, deactivated: y, beforeDestroy: x, beforeUnmount: S, destroyed: C, unmounted: w, render: ee, renderTracked: T, renderTriggered: te, errorCaptured: ne, serverPrefetch: E, expose: D, inheritAttrs: re, components: ie, directives: ae, filters: oe } = t;
	if (u && ri(u, r, null), s) for (let e in s) {
		let t = s[e];
		_(t) && (r[e] = t.bind(n));
	}
	if (i) {
		let t = i.call(n, n);
		b(t) && (e.data = /* @__PURE__ */ It(t));
	}
	if (ti = !0, o) for (let e in o) {
		let t = o[e], i = Z({
			get: _(t) ? t.bind(n, n) : _(t.get) ? t.get.bind(n, n) : a,
			set: !_(t) && _(t.set) ? t.set.bind(n) : a
		});
		Object.defineProperty(r, e, {
			enumerable: !0,
			configurable: !0,
			get: () => i.value,
			set: (e) => i.value = e
		});
	}
	if (c) for (let e in c) ai(c[e], r, n, e);
	if (l) {
		let e = _(l) ? l.call(n) : l;
		Reflect.ownKeys(e).forEach((t) => {
			Nn(t, e[t]);
		});
	}
	d && ii(d, e, "c");
	function O(e, t) {
		p(t) ? t.forEach((t) => e(t.bind(n))) : t && e(t.bind(n));
	}
	if (O(Mr, f), O(Nr, m), O(Pr, h), O(Fr, g), O(Er, v), O(Dr, y), O(Vr, ne), O(Br, T), O(zr, te), O(Ir, S), O(Lr, w), O(Rr, E), p(D)) if (D.length) {
		let t = e.exposed ||= {};
		D.forEach((e) => {
			Object.defineProperty(t, e, {
				get: () => n[e],
				set: (t) => n[e] = t,
				enumerable: !0
			});
		});
	} else e.exposed ||= {};
	ee && e.render === a && (e.render = ee), re != null && (e.inheritAttrs = re), ie && (e.components = ie), ae && (e.directives = ae), E && yr(e);
}
function ri(e, t, n = a) {
	p(e) && (e = di(e));
	for (let n in e) {
		let r = e[n], i;
		i = b(r) ? "default" in r ? Pn(r.from || n, r.default, !0) : Pn(r.from || n) : Pn(r), /* @__PURE__ */ F(i) ? Object.defineProperty(t, n, {
			enumerable: !0,
			configurable: !0,
			get: () => i.value,
			set: (e) => i.value = e
		}) : t[n] = i;
	}
}
function ii(e, t, n) {
	un(p(e) ? e.map((e) => e.bind(t.proxy)) : e.bind(t.proxy), t, n);
}
function ai(e, t, n, r) {
	let i = r.includes(".") ? Vn(n, r) : () => n[r];
	if (v(e)) {
		let n = t[e];
		_(n) && Rn(i, n);
	} else if (_(e)) Rn(i, e.bind(n));
	else if (b(e)) if (p(e)) e.forEach((e) => ai(e, t, n, r));
	else {
		let r = _(e.handler) ? e.handler.bind(n) : t[e.handler];
		_(r) && Rn(i, r, e);
	}
}
function oi(e) {
	let t = e.type, { mixins: n, extends: r } = t, { mixins: i, optionsCache: a, config: { optionMergeStrategies: o } } = e.appContext, s = a.get(t), c;
	return s ? c = s : !i.length && !n && !r ? c = t : (c = {}, i.length && i.forEach((e) => si(c, e, o, !0)), si(c, t, o)), b(t) && a.set(t, c), c;
}
function si(e, t, n, r = !1) {
	let { mixins: i, extends: a } = t;
	a && si(e, a, n, !0), i && i.forEach((t) => si(e, t, n, !0));
	for (let i in t) if (!(r && i === "expose")) {
		let r = ci[i] || n && n[i];
		e[i] = r ? r(e[i], t[i]) : t[i];
	}
	return e;
}
var ci = {
	data: li,
	props: mi,
	emits: mi,
	methods: pi,
	computed: pi,
	beforeCreate: fi,
	created: fi,
	beforeMount: fi,
	mounted: fi,
	beforeUpdate: fi,
	updated: fi,
	beforeDestroy: fi,
	beforeUnmount: fi,
	destroyed: fi,
	unmounted: fi,
	activated: fi,
	deactivated: fi,
	errorCaptured: fi,
	serverPrefetch: fi,
	components: pi,
	directives: pi,
	watch: hi,
	provide: li,
	inject: ui
};
function li(e, t) {
	return t ? e ? function() {
		return l(_(e) ? e.call(this, this) : e, _(t) ? t.call(this, this) : t);
	} : t : e;
}
function ui(e, t) {
	return pi(di(e), di(t));
}
function di(e) {
	if (p(e)) {
		let t = {};
		for (let n = 0; n < e.length; n++) t[e[n]] = e[n];
		return t;
	}
	return e;
}
function fi(e, t) {
	return e ? [...new Set([].concat(e, t))] : t;
}
function pi(e, t) {
	return e ? l(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function mi(e, t) {
	return e ? p(e) && p(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : l(/* @__PURE__ */ Object.create(null), $r(e), $r(t ?? {})) : t;
}
function hi(e, t) {
	if (!e) return t;
	if (!t) return e;
	let n = l(/* @__PURE__ */ Object.create(null), e);
	for (let r in t) n[r] = fi(e[r], t[r]);
	return n;
}
function gi() {
	return {
		app: null,
		config: {
			isNativeTag: o,
			performance: !1,
			globalProperties: {},
			optionMergeStrategies: {},
			errorHandler: void 0,
			warnHandler: void 0,
			compilerOptions: {}
		},
		mixins: [],
		components: {},
		directives: {},
		provides: /* @__PURE__ */ Object.create(null),
		optionsCache: /* @__PURE__ */ new WeakMap(),
		propsCache: /* @__PURE__ */ new WeakMap(),
		emitsCache: /* @__PURE__ */ new WeakMap()
	};
}
var _i = 0;
function vi(e, t) {
	return function(n, r = null) {
		_(n) || (n = l({}, n)), r != null && !b(r) && (r = null);
		let i = gi(), a = /* @__PURE__ */ new WeakSet(), o = [], s = !1, c = i.app = {
			_uid: _i++,
			_component: n,
			_props: r,
			_container: null,
			_context: i,
			_instance: null,
			version: Qa,
			get config() {
				return i.config;
			},
			set config(e) {},
			use(e, ...t) {
				return a.has(e) || (e && _(e.install) ? (a.add(e), e.install(c, ...t)) : _(e) && (a.add(e), e(c, ...t))), c;
			},
			mixin(e) {
				return i.mixins.includes(e) || i.mixins.push(e), c;
			},
			component(e, t) {
				return t ? (i.components[e] = t, c) : i.components[e];
			},
			directive(e, t) {
				return t ? (i.directives[e] = t, c) : i.directives[e];
			},
			mount(a, o, l) {
				if (!s) {
					let u = c._ceVNode || q(n, r);
					return u.appContext = i, l === !0 ? l = "svg" : l === !1 && (l = void 0), o && t ? t(u, a) : e(u, a, l), s = !0, c._container = a, a.__vue_app__ = c, Ja(u.component);
				}
			},
			onUnmount(e) {
				o.push(e);
			},
			unmount() {
				s && (un(o, c._instance, 16), e(null, c._container), delete c._container.__vue_app__);
			},
			provide(e, t) {
				return i.provides[e] = t, c;
			},
			runWithContext(e) {
				let t = yi;
				yi = c;
				try {
					return e();
				} finally {
					yi = t;
				}
			}
		};
		return c;
	};
}
var yi = null;
function bi(e, t, n = r) {
	let i = Na(), a = D(t), o = ie(t), s = xi(e, a), c = $t((s, c) => {
		let l, u = r, d;
		return Ln(() => {
			let t = e[a];
			O(l, t) && (l = t, c());
		}), {
			get() {
				return s(), n.get ? n.get(l) : l;
			},
			set(e) {
				let s = n.set ? n.set(e) : e;
				if (!O(s, l) && !(u !== r && O(e, u))) return;
				let f = i.vnode.props, p = !!(f && (t in f || a in f || o in f) && (`onUpdate:${t}` in f || `onUpdate:${a}` in f || `onUpdate:${o}` in f));
				p || (l = e, c()), i.emit(`update:${t}`, s), O(e, u) && (O(e, s) && !O(s, d) || p && u !== r && !O(s, l)) && c(), u = e, d = s;
			}
		};
	});
	return c[Symbol.iterator] = () => {
		let e = 0;
		return { next() {
			return e < 2 ? {
				value: e++ ? s || r : c,
				done: !1
			} : { done: !0 };
		} };
	}, c;
}
var xi = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${D(t)}Modifiers`] || e[`${ie(t)}Modifiers`];
function Si(e, t, ...n) {
	if (e.isUnmounted) return;
	let i = e.vnode.props || r, a = n, o = t.startsWith("update:"), s = o && xi(i, t.slice(7));
	s && (s.trim && (a = n.map((e) => v(e) ? e.trim() : e)), s.number && (a = n.map(le)));
	let c, l = i[c = oe(t)] || i[c = oe(D(t))];
	!l && o && (l = i[c = oe(ie(t))]), l && un(l, e, 6, a);
	let u = i[c + "Once"];
	if (u) {
		if (!e.emitted) e.emitted = {};
		else if (e.emitted[c]) return;
		e.emitted[c] = !0, un(u, e, 6, a);
	}
}
var Ci = /* @__PURE__ */ new WeakMap();
function wi(e, t, n = !1) {
	let r = n ? Ci : t.emitsCache, i = r.get(e);
	if (i !== void 0) return i;
	let a = e.emits, o = {}, s = !1;
	if (!_(e)) {
		let r = (e) => {
			let n = wi(e, t, !0);
			n && (s = !0, l(o, n));
		};
		!n && t.mixins.length && t.mixins.forEach(r), e.extends && r(e.extends), e.mixins && e.mixins.forEach(r);
	}
	return !a && !s ? (b(e) && r.set(e, null), null) : (p(a) ? a.forEach((e) => o[e] = null) : l(o, a), b(e) && r.set(e, o), o);
}
function Ti(e, t) {
	return !e || !s(t) ? !1 : (t = t.slice(2).replace(/Once$/, ""), f(e, t[0].toLowerCase() + t.slice(1)) || f(e, ie(t)) || f(e, t));
}
function Ei(e) {
	let { type: t, vnode: n, proxy: r, withProxy: i, propsOptions: [a], slots: o, attrs: s, emit: l, render: u, renderCache: d, props: f, data: p, setupState: m, ctx: h, inheritAttrs: g } = e, _ = An(e), v, y;
	try {
		if (n.shapeFlag & 4) {
			let e = i || r, t = e;
			v = Ta(u.call(t, e, d, f, m, p, h)), y = s;
		} else {
			let e = t;
			v = Ta(e.length > 1 ? e(f, {
				attrs: s,
				slots: o,
				emit: l
			}) : e(f, null)), y = t.props ? s : Di(s);
		}
	} catch (t) {
		fa.length = 0, dn(t, e, 1), v = q(H);
	}
	let b = v;
	if (y && g !== !1) {
		let e = Object.keys(y), { shapeFlag: t } = b;
		e.length && t & 7 && (a && e.some(c) && (y = Oi(y, a)), b = wa(b, y, !1, !0));
	}
	return n.dirs && (b = wa(b, null, !1, !0), b.dirs = b.dirs ? b.dirs.concat(n.dirs) : n.dirs), n.transition && hr(b, n.transition), v = b, An(_), v;
}
var Di = (e) => {
	let t;
	for (let n in e) (n === "class" || n === "style" || s(n)) && ((t ||= {})[n] = e[n]);
	return t;
}, Oi = (e, t) => {
	let n = {};
	for (let r in e) (!c(r) || !(r.slice(9) in t)) && (n[r] = e[r]);
	return n;
};
function ki(e, t, n) {
	let { props: r, children: i, component: a } = e, { props: o, children: s, patchFlag: c } = t, l = a.emitsOptions;
	if (t.dirs || t.transition) return !0;
	if (n && c >= 0) {
		if (c & 1024) return !0;
		if (c & 16) return r ? Ai(r, o, l) : !!o;
		if (c & 8) {
			let e = t.dynamicProps;
			for (let t = 0; t < e.length; t++) {
				let n = e[t];
				if (ji(o, r, n) && !Ti(l, n)) return !0;
			}
		}
	} else return (i || s) && (!s || !s.$stable) ? !0 : r === o ? !1 : r ? o ? Ai(r, o, l) : !0 : !!o;
	return !1;
}
function Ai(e, t, n) {
	let r = Object.keys(t);
	if (r.length !== Object.keys(e).length) return !0;
	for (let i = 0; i < r.length; i++) {
		let a = r[i];
		if (ji(t, e, a) && !Ti(n, a)) return !0;
	}
	return !1;
}
function ji(e, t, n) {
	let r = e[n], i = t[n];
	return n === "style" && b(r) && b(i) ? !Se(r, i) : r !== i;
}
function Mi({ vnode: e, parent: t, suspense: n }, r) {
	for (; t;) {
		let n = t.subTree;
		if (n.suspense && n.suspense.activeBranch === e && (n.suspense.vnode.el = n.el = r, e = n), n === e) (e = t.vnode).el = r, t = t.parent;
		else break;
	}
	n && n.activeBranch === e && (n.vnode.el = r);
}
var Ni = {}, Pi = () => Object.create(Ni), Fi = (e) => Object.getPrototypeOf(e) === Ni;
function Ii(e, t, n, r = !1) {
	let i = {}, a = Pi();
	e.propsDefaults = /* @__PURE__ */ Object.create(null), Ri(e, t, i, a);
	for (let t in e.propsOptions[0]) t in i || (i[t] = void 0);
	n ? e.props = r ? i : /* @__PURE__ */ Lt(i) : e.type.props ? e.props = i : e.props = a, e.attrs = a;
}
function Li(e, t, n, r) {
	let { props: i, attrs: a, vnode: { patchFlag: o } } = e, s = /* @__PURE__ */ P(i), [c] = e.propsOptions, l = !1;
	if ((r || o > 0) && !(o & 16)) {
		if (o & 8) {
			let n = e.vnode.dynamicProps;
			for (let r = 0; r < n.length; r++) {
				let o = n[r];
				if (Ti(e.emitsOptions, o)) continue;
				let u = t[o];
				if (c) if (f(a, o)) u !== a[o] && (a[o] = u, l = !0);
				else {
					let t = D(o);
					i[t] = zi(c, s, t, u, e, !1);
				}
				else u !== a[o] && (a[o] = u, l = !0);
			}
		}
	} else {
		Ri(e, t, i, a) && (l = !0);
		let r;
		for (let a in s) (!t || !f(t, a) && ((r = ie(a)) === a || !f(t, r))) && (c ? n && (n[a] !== void 0 || n[r] !== void 0) && (i[a] = zi(c, s, a, void 0, e, !0)) : delete i[a]);
		if (a !== s) for (let e in a) (!t || !f(t, e)) && (delete a[e], l = !0);
	}
	l && nt(e.attrs, "set", "");
}
function Ri(e, t, n, i) {
	let [a, o] = e.propsOptions, s = !1, c;
	if (t) for (let r in t) {
		if (te(r)) continue;
		let l = t[r], u;
		a && f(a, u = D(r)) ? !o || !o.includes(u) ? n[u] = l : (c ||= {})[u] = l : Ti(e.emitsOptions, r) || (!(r in i) || l !== i[r]) && (i[r] = l, s = !0);
	}
	if (o) {
		let t = /* @__PURE__ */ P(n), i = c || r;
		for (let r = 0; r < o.length; r++) {
			let s = o[r];
			n[s] = zi(a, t, s, i[s], e, !f(i, s));
		}
	}
	return s;
}
function zi(e, t, n, r, i, a) {
	let o = e[n];
	if (o != null) {
		let e = f(o, "default");
		if (e && r === void 0) {
			let e = o.default;
			if (o.type !== Function && !o.skipFactory && _(e)) {
				let { propsDefaults: a } = i;
				if (n in a) r = a[n];
				else {
					let o = Ia(i);
					r = a[n] = e.call(null, t), o();
				}
			} else r = e;
			i.ce && i.ce._setProp(n, r);
		}
		o[0] && (a && !e ? r = !1 : o[1] && (r === "" || r === ie(n)) && (r = !0));
	}
	return r;
}
var Bi = /* @__PURE__ */ new WeakMap();
function Vi(e, t, n = !1) {
	let a = n ? Bi : t.propsCache, o = a.get(e);
	if (o) return o;
	let s = e.props, c = {}, u = [], d = !1;
	if (!_(e)) {
		let r = (e) => {
			d = !0;
			let [n, r] = Vi(e, t, !0);
			l(c, n), r && u.push(...r);
		};
		!n && t.mixins.length && t.mixins.forEach(r), e.extends && r(e.extends), e.mixins && e.mixins.forEach(r);
	}
	if (!s && !d) return b(e) && a.set(e, i), i;
	if (p(s)) for (let e = 0; e < s.length; e++) {
		let t = D(s[e]);
		Hi(t) && (c[t] = r);
	}
	else if (s) for (let e in s) {
		let t = D(e);
		if (Hi(t)) {
			let n = s[e], r = c[t] = p(n) || _(n) ? { type: n } : l({}, n), i = r.type, a = !1, o = !0;
			if (p(i)) for (let e = 0; e < i.length; ++e) {
				let t = i[e], n = _(t) && t.name;
				if (n === "Boolean") {
					a = !0;
					break;
				} else n === "String" && (o = !1);
			}
			else a = _(i) && i.name === "Boolean";
			r[0] = a, r[1] = o, (a || f(r, "default")) && u.push(t);
		}
	}
	let m = [c, u];
	return b(e) && a.set(e, m), m;
}
function Hi(e) {
	return e[0] !== "$" && !te(e);
}
var Ui = (e) => e === "_" || e === "_ctx" || e === "$stable", Wi = (e) => p(e) ? e.map(Ta) : [Ta(e)], Gi = (e, t, n) => {
	if (t._n) return t;
	let r = jn((...e) => Wi(t(...e)), n);
	return r._c = !1, r;
}, Ki = (e, t, n) => {
	let r = e._ctx;
	for (let n in e) {
		if (Ui(n)) continue;
		let i = e[n];
		if (_(i)) t[n] = Gi(n, i, r);
		else if (i != null) {
			let e = Wi(i);
			t[n] = () => e;
		}
	}
}, qi = (e, t) => {
	let n = Wi(t);
	e.slots.default = () => n;
}, Ji = (e, t, n) => {
	for (let r in t) (n || !Ui(r)) && (e[r] = t[r]);
}, Yi = (e, t, n) => {
	let r = e.slots = Pi();
	if (e.vnode.shapeFlag & 32) {
		let e = t._;
		e ? (Ji(r, t, n), n && ce(r, "_", e, !0)) : Ki(t, r);
	} else t && qi(e, t);
}, Xi = (e, t, n) => {
	let { vnode: i, slots: a } = e, o = !0, s = r;
	if (i.shapeFlag & 32) {
		let e = t._;
		e ? n && e === 1 ? o = !1 : Ji(a, t, n) : (o = !t.$stable, Ki(t, a)), s = t;
	} else t && (qi(e, t), s = { default: 1 });
	if (o) for (let e in a) !Ui(e) && s[e] == null && delete a[e];
}, Zi = la;
function Qi(e) {
	return $i(e);
}
function $i(e, t) {
	let n = fe();
	n.__VUE__ = !0;
	let { insert: o, remove: s, patchProp: c, createElement: l, createText: u, createComment: d, setText: f, setElementText: p, parentNode: m, nextSibling: h, setScopeId: g = a, insertStaticContent: _ } = e, v = (e, t, n, r = null, i = null, a = null, o = void 0, s = null, c = !!t.dynamicChildren) => {
		if (e === t) return;
		e && !ya(e, t) && (r = ye(e), he(e, i, a, !0), e = null), t.patchFlag === -2 && (c = !1, t.dynamicChildren = null);
		let { type: l, ref: u, shapeFlag: d } = t;
		switch (l) {
			case ua:
				y(e, t, n, r);
				break;
			case H:
				b(e, t, n, r);
				break;
			case da:
				e ?? x(t, n, r, o);
				break;
			case V:
				ie(e, t, n, r, i, a, o, s, c);
				break;
			default: d & 1 ? w(e, t, n, r, i, a, o, s, c) : d & 6 ? ae(e, t, n, r, i, a, o, s, c) : (d & 64 || d & 128) && l.process(e, t, n, r, i, a, o, s, c, Se);
		}
		u != null && i ? Sr(u, e && e.ref, a, t || e, !t) : u == null && e && e.ref != null && Sr(e.ref, null, a, e, !0);
	}, y = (e, t, n, r) => {
		if (e == null) o(t.el = u(t.children), n, r);
		else {
			let n = t.el = e.el;
			t.children !== e.children && f(n, t.children);
		}
	}, b = (e, t, n, r) => {
		e == null ? o(t.el = d(t.children || ""), n, r) : t.el = e.el;
	}, x = (e, t, n, r) => {
		[e.el, e.anchor] = _(e.children, t, n, r, e.el, e.anchor);
	}, S = ({ el: e, anchor: t }, n, r) => {
		let i;
		for (; e && e !== t;) i = h(e), o(e, n, r), e = i;
		o(t, n, r);
	}, C = ({ el: e, anchor: t }) => {
		let n;
		for (; e && e !== t;) n = h(e), s(e), e = n;
		s(t);
	}, w = (e, t, n, r, i, a, o, s, c) => {
		if (t.type === "svg" ? o = "svg" : t.type === "math" && (o = "mathml"), e == null) ee(t, n, r, i, a, o, s, c);
		else {
			let n = e.el && e.el._isVueCE ? e.el : null;
			try {
				n && n._beginPatch(), E(e, t, i, a, o, s, c);
			} finally {
				n && n._endPatch();
			}
		}
	}, ee = (e, t, n, r, i, a, s, u) => {
		let d, f, { props: m, shapeFlag: h, transition: g, dirs: _ } = e;
		if (d = e.el = l(e.type, a, m && m.is, m), h & 8 ? p(d, e.children) : h & 16 && ne(e.children, d, null, r, i, ea(e, a), s, u), _ && Mn(e, null, r, "created"), T(d, e, e.scopeId, s, r), m) {
			for (let e in m) e !== "value" && !te(e) && c(d, e, null, m[e], a, r);
			"value" in m && c(d, "value", null, m.value, a), (f = m.onVnodeBeforeMount) && ka(f, r, e);
		}
		_ && Mn(e, null, r, "beforeMount");
		let v = na(i, g);
		v && g.beforeEnter(d), o(d, t, n), ((f = m && m.onVnodeMounted) || v || _) && Zi(() => {
			try {
				f && ka(f, r, e), v && g.enter(d), _ && Mn(e, null, r, "mounted");
			} finally {}
		}, i);
	}, T = (e, t, n, r, i) => {
		if (n && g(e, n), r) for (let t = 0; t < r.length; t++) g(e, r[t]);
		if (i) {
			let n = i.subTree;
			if (t === n || ca(n.type) && (n.ssContent === t || n.ssFallback === t)) {
				let t = i.vnode;
				T(e, t, t.scopeId, t.slotScopeIds, i.parent);
			}
		}
	}, ne = (e, t, n, r, i, a, o, s, c = 0) => {
		for (let l = c; l < e.length; l++) v(null, e[l] = s ? Ea(e[l]) : Ta(e[l]), t, n, r, i, a, o, s);
	}, E = (e, t, n, i, a, o, s) => {
		let l = t.el = e.el, { patchFlag: u, dynamicChildren: d, dirs: f } = t;
		u |= e.patchFlag & 16;
		let m = e.props || r, h = t.props || r, g;
		if (n && ta(n, !1), (g = h.onVnodeBeforeUpdate) && ka(g, n, t, e), f && Mn(t, e, n, "beforeUpdate"), n && ta(n, !0), (m.innerHTML && h.innerHTML == null || m.textContent && h.textContent == null) && p(l, ""), d ? D(e.dynamicChildren, d, l, n, i, ea(t, a), o) : s || ue(e, t, l, null, n, i, ea(t, a), o, !1), u > 0) {
			if (u & 16) re(l, m, h, n, a);
			else if (u & 2 && m.class !== h.class && c(l, "class", null, h.class, a), u & 4 && c(l, "style", m.style, h.style, a), u & 8) {
				let e = t.dynamicProps;
				for (let t = 0; t < e.length; t++) {
					let r = e[t], i = m[r], o = h[r];
					(o !== i || r === "value") && c(l, r, i, o, a, n);
				}
			}
			u & 1 && e.children !== t.children && p(l, t.children);
		} else !s && d == null && re(l, m, h, n, a);
		((g = h.onVnodeUpdated) || f) && Zi(() => {
			g && ka(g, n, t, e), f && Mn(t, e, n, "updated");
		}, i);
	}, D = (e, t, n, r, i, a, o) => {
		for (let s = 0; s < t.length; s++) {
			let c = e[s], l = t[s];
			v(c, l, c.el && (c.type === V || !ya(c, l) || c.shapeFlag & 198) ? m(c.el) : n, null, r, i, a, o, !0);
		}
	}, re = (e, t, n, i, a) => {
		if (t !== n) {
			if (t !== r) for (let r in t) !te(r) && !(r in n) && c(e, r, t[r], null, a, i);
			for (let r in n) {
				if (te(r)) continue;
				let o = n[r], s = t[r];
				o !== s && r !== "value" && c(e, r, s, o, a, i);
			}
			"value" in n && c(e, "value", t.value, n.value, a);
		}
	}, ie = (e, t, n, r, i, a, s, c, l) => {
		let d = t.el = e ? e.el : u(""), f = t.anchor = e ? e.anchor : u(""), { patchFlag: p, dynamicChildren: m, slotScopeIds: h } = t;
		h && (c = c ? c.concat(h) : h), e == null ? (o(d, n, r), o(f, n, r), ne(t.children || [], n, f, i, a, s, c, l)) : p > 0 && p & 64 && m && e.dynamicChildren && e.dynamicChildren.length === m.length ? (D(e.dynamicChildren, m, n, i, a, s, c), (t.key != null || i && t === i.subTree) && ra(e, t, !0)) : ue(e, t, n, f, i, a, s, c, l);
	}, ae = (e, t, n, r, i, a, o, s, c) => {
		t.slotScopeIds = s, e == null ? t.shapeFlag & 512 ? i.ctx.activate(t, n, r, o, c) : oe(t, n, r, i, a, o, c) : O(e, t, c);
	}, oe = (e, t, n, r, i, a, o) => {
		let s = e.component = Ma(e, r, i);
		if (Tr(e) && (s.ctx.renderer = Se), Ba(s, !1, o), s.asyncDep) {
			if (i && i.registerDep(s, ce, o), !e.el) {
				let r = s.subTree = q(H);
				b(null, r, t, n), e.placeholder = r.el;
			}
		} else ce(s, e, t, n, i, a, o);
	}, O = (e, t, n) => {
		let r = t.component = e.component;
		if (ki(e, t, n)) if (r.asyncDep && !r.asyncResolved) {
			le(r, t, n);
			return;
		} else r.next = t, r.update();
		else t.el = e.el, r.vnode = t;
	}, ce = (e, t, n, r, i, a, o) => {
		let s = () => {
			if (e.isMounted) {
				let { next: t, bu: n, u: r, parent: s, vnode: c } = e;
				{
					let n = aa(e);
					if (n) {
						t && (t.el = c.el, le(e, t, o)), n.asyncDep.then(() => {
							Zi(() => {
								e.isUnmounted || l();
							}, i);
						});
						return;
					}
				}
				let u = t, d;
				ta(e, !1), t ? (t.el = c.el, le(e, t, o)) : t = c, n && se(n), (d = t.props && t.props.onVnodeBeforeUpdate) && ka(d, s, t, c), ta(e, !0);
				let f = Ei(e), p = e.subTree;
				e.subTree = f, v(p, f, m(p.el), ye(p), e, i, a), t.el = f.el, u === null && Mi(e, f.el), r && Zi(r, i), (d = t.props && t.props.onVnodeUpdated) && Zi(() => ka(d, s, t, c), i);
			} else {
				let o, { el: s, props: c } = t, { bm: l, m: u, parent: d, root: f, type: p } = e, m = wr(t);
				if (ta(e, !1), l && se(l), !m && (o = c && c.onVnodeBeforeMount) && ka(o, d, t), ta(e, !0), s && we) {
					let t = () => {
						e.subTree = Ei(e), we(s, e.subTree, e, i, null);
					};
					m && p.__asyncHydrate ? p.__asyncHydrate(s, e, t) : t();
				} else {
					f.ce && f.ce._hasShadowRoot() && f.ce._injectChildStyle(p, e.parent ? e.parent.type : void 0);
					let o = e.subTree = Ei(e);
					v(null, o, n, r, e, i, a), t.el = o.el;
				}
				if (u && Zi(u, i), !m && (o = c && c.onVnodeMounted)) {
					let e = t;
					Zi(() => ka(o, d, e), i);
				}
				(t.shapeFlag & 256 || d && wr(d.vnode) && d.vnode.shapeFlag & 256) && e.a && Zi(e.a, i), e.isMounted = !0, t = n = r = null;
			}
		};
		e.scope.on();
		let c = e.effect = new Ae(s);
		e.scope.off();
		let l = e.update = c.run.bind(c), u = e.job = c.runIfDirty.bind(c);
		u.i = e, u.id = e.uid, c.scheduler = () => Sn(u), ta(e, !0), l();
	}, le = (e, t, n) => {
		t.component = e;
		let r = e.vnode.props;
		e.vnode = t, e.next = null, Li(e, t.props, r, n), Xi(e, t.children, n), Ge(), Tn(e), Ke();
	}, ue = (e, t, n, r, i, a, o, s, c = !1) => {
		let l = e && e.children, u = e ? e.shapeFlag : 0, d = t.children, { patchFlag: f, shapeFlag: m } = t;
		if (f > 0) {
			if (f & 128) {
				pe(l, d, n, r, i, a, o, s, c);
				return;
			} else if (f & 256) {
				de(l, d, n, r, i, a, o, s, c);
				return;
			}
		}
		m & 8 ? (u & 16 && ve(l, i, a), d !== l && p(n, d)) : u & 16 ? m & 16 ? pe(l, d, n, r, i, a, o, s, c) : ve(l, i, a, !0) : (u & 8 && p(n, ""), m & 16 && ne(d, n, r, i, a, o, s, c));
	}, de = (e, t, n, r, a, o, s, c, l) => {
		e ||= i, t ||= i;
		let u = e.length, d = t.length, f = Math.min(u, d), p;
		for (p = 0; p < f; p++) {
			let r = t[p] = l ? Ea(t[p]) : Ta(t[p]);
			v(e[p], r, n, null, a, o, s, c, l);
		}
		u > d ? ve(e, a, o, !0, !1, f) : ne(t, n, r, a, o, s, c, l, f);
	}, pe = (e, t, n, r, a, o, s, c, l) => {
		let u = 0, d = t.length, f = e.length - 1, p = d - 1;
		for (; u <= f && u <= p;) {
			let r = e[u], i = t[u] = l ? Ea(t[u]) : Ta(t[u]);
			if (ya(r, i)) v(r, i, n, null, a, o, s, c, l);
			else break;
			u++;
		}
		for (; u <= f && u <= p;) {
			let r = e[f], i = t[p] = l ? Ea(t[p]) : Ta(t[p]);
			if (ya(r, i)) v(r, i, n, null, a, o, s, c, l);
			else break;
			f--, p--;
		}
		if (u > f) {
			if (u <= p) {
				let e = p + 1, i = e < d ? t[e].el : r;
				for (; u <= p;) v(null, t[u] = l ? Ea(t[u]) : Ta(t[u]), n, i, a, o, s, c, l), u++;
			}
		} else if (u > p) for (; u <= f;) he(e[u], a, o, !0), u++;
		else {
			let m = u, h = u, g = /* @__PURE__ */ new Map();
			for (u = h; u <= p; u++) {
				let e = t[u] = l ? Ea(t[u]) : Ta(t[u]);
				e.key != null && g.set(e.key, u);
			}
			let _, y = 0, b = p - h + 1, x = !1, S = 0, C = Array(b);
			for (u = 0; u < b; u++) C[u] = 0;
			for (u = m; u <= f; u++) {
				let r = e[u];
				if (y >= b) {
					he(r, a, o, !0);
					continue;
				}
				let i;
				if (r.key != null) i = g.get(r.key);
				else for (_ = h; _ <= p; _++) if (C[_ - h] === 0 && ya(r, t[_])) {
					i = _;
					break;
				}
				i === void 0 ? he(r, a, o, !0) : (C[i - h] = u + 1, i >= S ? S = i : x = !0, v(r, t[i], n, null, a, o, s, c, l), y++);
			}
			let w = x ? ia(C) : i;
			for (_ = w.length - 1, u = b - 1; u >= 0; u--) {
				let e = h + u, i = t[e], f = t[e + 1], p = e + 1 < d ? f.el || sa(f) : r;
				C[u] === 0 ? v(null, i, n, p, a, o, s, c, l) : x && (_ < 0 || u !== w[_] ? me(i, n, p, 2) : _--);
			}
		}
	}, me = (e, t, n, r, i = null) => {
		let { el: a, type: c, transition: l, children: u, shapeFlag: d } = e;
		if (d & 6) {
			me(e.component.subTree, t, n, r);
			return;
		}
		if (d & 128) {
			e.suspense.move(t, n, r);
			return;
		}
		if (d & 64) {
			c.move(e, t, n, Se);
			return;
		}
		if (c === V) {
			o(a, t, n);
			for (let e = 0; e < u.length; e++) me(u[e], t, n, r);
			o(e.anchor, t, n);
			return;
		}
		if (c === da) {
			S(e, t, n);
			return;
		}
		if (r !== 2 && d & 1 && l) if (r === 0) l.persisted && !a[nr] ? o(a, t, n) : (l.beforeEnter(a), o(a, t, n), Zi(() => l.enter(a), i));
		else {
			let { leave: r, delayLeave: i, afterLeave: c } = l, u = () => {
				e.ctx.isUnmounted ? s(a) : o(a, t, n);
			}, d = () => {
				let e = a._isLeaving || !!a[nr];
				a._isLeaving && a[nr](!0), l.persisted && !e ? u() : r(a, () => {
					u(), c && c();
				});
			};
			i ? i(a, u, d) : d();
		}
		else o(a, t, n);
	}, he = (e, t, n, r = !1, i = !1) => {
		let { type: a, props: o, ref: s, children: c, dynamicChildren: l, shapeFlag: u, patchFlag: d, dirs: f, cacheIndex: p, memo: m } = e;
		if (d === -2 && (i = !1), s != null && (Ge(), Sr(s, null, n, e, !0), Ke()), p != null && (t.renderCache[p] = void 0), u & 256) {
			t.ctx.deactivate(e);
			return;
		}
		let h = u & 1 && f, g = !wr(e), _;
		if (g && (_ = o && o.onVnodeBeforeUnmount) && ka(_, t, e), u & 6) k(e.component, n, r);
		else {
			if (u & 128) {
				e.suspense.unmount(n, r);
				return;
			}
			h && Mn(e, null, t, "beforeUnmount"), u & 64 ? e.type.remove(e, t, n, Se, r) : l && !l.hasOnce && (a !== V || d > 0 && d & 64) ? ve(l, t, n, !1, !0) : (a === V && d & 384 || !i && u & 16) && ve(c, t, n), r && ge(e);
		}
		let v = m != null && p == null;
		(g && (_ = o && o.onVnodeUnmounted) || h || v) && Zi(() => {
			_ && ka(_, t, e), h && Mn(e, null, t, "unmounted"), v && (e.el = null);
		}, n);
	}, ge = (e) => {
		let { type: t, el: n, anchor: r, transition: i } = e;
		if (t === V) {
			_e(n, r);
			return;
		}
		if (t === da) {
			C(e);
			return;
		}
		let a = () => {
			s(n), i && !i.persisted && i.afterLeave && i.afterLeave();
		};
		if (e.shapeFlag & 1 && i && !i.persisted) {
			let { leave: t, delayLeave: r } = i, o = () => t(n, a);
			r ? r(e.el, a, o) : o();
		} else a();
	}, _e = (e, t) => {
		let n;
		for (; e !== t;) n = h(e), s(e), e = n;
		s(t);
	}, k = (e, t, n) => {
		let { bum: r, scope: i, job: a, subTree: o, um: s, m: c, a: l } = e;
		oa(c), oa(l), r && se(r), i.stop(), a && (a.flags |= 8, he(o, e, t, n)), s && Zi(s, t), Zi(() => {
			e.isUnmounted = !0;
		}, t);
	}, ve = (e, t, n, r = !1, i = !1, a = 0) => {
		for (let o = a; o < e.length; o++) he(e[o], t, n, r, i);
	}, ye = (e) => {
		if (e.shapeFlag & 6) return ye(e.component.subTree);
		if (e.shapeFlag & 128) return e.suspense.next();
		let t = h(e.anchor || e.el), n = t && t[Un];
		return n ? h(n) : t;
	}, be = !1, xe = (e, t, n) => {
		let r;
		e == null ? t._vnode && (he(t._vnode, null, null, !0), r = t._vnode.component) : v(t._vnode || null, e, t, null, null, null, n), t._vnode = e, be ||= (be = !0, Tn(r), En(), !1);
	}, Se = {
		p: v,
		um: he,
		m: me,
		r: ge,
		mt: oe,
		mc: ne,
		pc: ue,
		pbc: D,
		n: ye,
		o: e
	}, Ce, we;
	return t && ([Ce, we] = t(Se)), {
		render: xe,
		hydrate: Ce,
		createApp: vi(xe, Ce)
	};
}
function ea({ type: e, props: t }, n) {
	return n === "svg" && e === "foreignObject" || n === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : n;
}
function ta({ effect: e, job: t }, n) {
	n ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function na(e, t) {
	return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function ra(e, t, n = !1) {
	let r = e.children, i = t.children;
	if (p(r) && p(i)) for (let e = 0; e < r.length; e++) {
		let t = r[e], a = i[e];
		a.shapeFlag & 1 && !a.dynamicChildren && ((a.patchFlag <= 0 || a.patchFlag === 32) && (a = i[e] = Ea(i[e]), a.el = t.el), !n && a.patchFlag !== -2 && ra(t, a)), a.type === ua && (a.patchFlag === -1 && (a = i[e] = Ea(a)), a.el = t.el), a.type === H && !a.el && (a.el = t.el);
	}
}
function ia(e) {
	let t = e.slice(), n = [0], r, i, a, o, s, c = e.length;
	for (r = 0; r < c; r++) {
		let c = e[r];
		if (c !== 0) {
			if (i = n[n.length - 1], e[i] < c) {
				t[r] = i, n.push(r);
				continue;
			}
			for (a = 0, o = n.length - 1; a < o;) s = a + o >> 1, e[n[s]] < c ? a = s + 1 : o = s;
			c < e[n[a]] && (a > 0 && (t[r] = n[a - 1]), n[a] = r);
		}
	}
	for (a = n.length, o = n[a - 1]; a-- > 0;) n[a] = o, o = t[o];
	return n;
}
function aa(e) {
	let t = e.subTree.component;
	if (t) return t.asyncDep && !t.asyncResolved ? t : aa(t);
}
function oa(e) {
	if (e) for (let t = 0; t < e.length; t++) e[t].flags |= 8;
}
function sa(e) {
	if (e.placeholder) return e.placeholder;
	let t = e.component;
	return t ? sa(t.subTree) : null;
}
var ca = (e) => e.__isSuspense;
function la(e, t) {
	t && t.pendingBranch ? p(e) ? t.effects.push(...e) : t.effects.push(e) : wn(e);
}
var V = /* @__PURE__ */ Symbol.for("v-fgt"), ua = /* @__PURE__ */ Symbol.for("v-txt"), H = /* @__PURE__ */ Symbol.for("v-cmt"), da = /* @__PURE__ */ Symbol.for("v-stc"), fa = [], pa = null;
function U(e = !1) {
	fa.push(pa = e ? null : []);
}
function ma() {
	fa.pop(), pa = fa[fa.length - 1] || null;
}
var ha = 1;
function ga(e, t = !1) {
	ha += e, e < 0 && pa && t && (pa.hasOnce = !0);
}
function _a(e) {
	return e.dynamicChildren = ha > 0 ? pa || i : null, ma(), ha > 0 && pa && pa.push(e), e;
}
function W(e, t, n, r, i, a) {
	return _a(K(e, t, n, r, i, a, !0));
}
function G(e, t, n, r, i) {
	return _a(q(e, t, n, r, i, !0));
}
function va(e) {
	return e ? e.__v_isVNode === !0 : !1;
}
function ya(e, t) {
	return e.type === t.type && e.key === t.key;
}
var ba = ({ key: e }) => e ?? null, xa = ({ ref: e, ref_key: t, ref_for: n }) => (typeof e == "number" && (e = "" + e), e == null ? null : v(e) || /* @__PURE__ */ F(e) || _(e) ? {
	i: R,
	r: e,
	k: t,
	f: !!n
} : e);
function K(e, t = null, n = null, r = 0, i = null, a = e === V ? 0 : 1, o = !1, s = !1) {
	let c = {
		__v_isVNode: !0,
		__v_skip: !0,
		type: e,
		props: t,
		key: t && ba(t),
		ref: t && xa(t),
		scopeId: kn,
		slotScopeIds: null,
		children: n,
		component: null,
		suspense: null,
		ssContent: null,
		ssFallback: null,
		dirs: null,
		transition: null,
		el: null,
		anchor: null,
		target: null,
		targetStart: null,
		targetAnchor: null,
		staticCount: 0,
		shapeFlag: a,
		patchFlag: r,
		dynamicProps: i,
		dynamicChildren: null,
		appContext: null,
		ctx: R
	};
	return s ? (Da(c, n), a & 128 && e.normalize(c)) : n && (c.shapeFlag |= v(n) ? 8 : 16), ha > 0 && !o && pa && (c.patchFlag > 0 || a & 6) && c.patchFlag !== 32 && pa.push(c), c;
}
var q = Sa;
function Sa(e, t = null, n = null, r = 0, i = null, a = !1) {
	if ((!e || e === Ur) && (e = H), va(e)) {
		let r = wa(e, t, !0);
		return n && Da(r, n), ha > 0 && !a && pa && (r.shapeFlag & 6 ? pa[pa.indexOf(e)] = r : pa.push(r)), r.patchFlag = -2, r;
	}
	if (Xa(e) && (e = e.__vccOpts), t) {
		t = Ca(t);
		let { class: e, style: n } = t;
		e && !v(e) && (t.class = k(e)), b(n) && (/* @__PURE__ */ Ut(n) && !p(n) && (n = l({}, n)), t.style = pe(n));
	}
	let o = v(e) ? 1 : ca(e) ? 128 : Wn(e) ? 64 : b(e) ? 4 : _(e) ? 2 : 0;
	return K(e, t, n, r, i, o, a, !0);
}
function Ca(e) {
	return e ? /* @__PURE__ */ Ut(e) || Fi(e) ? l({}, e) : e : null;
}
function wa(e, t, n = !1, r = !1) {
	let { props: i, ref: a, patchFlag: o, children: s, transition: c } = e, l = t ? Oa(i || {}, t) : i, u = {
		__v_isVNode: !0,
		__v_skip: !0,
		type: e.type,
		props: l,
		key: l && ba(l),
		ref: t && t.ref ? n && a ? p(a) ? a.concat(xa(t)) : [a, xa(t)] : xa(t) : a,
		scopeId: e.scopeId,
		slotScopeIds: e.slotScopeIds,
		children: s,
		target: e.target,
		targetStart: e.targetStart,
		targetAnchor: e.targetAnchor,
		staticCount: e.staticCount,
		shapeFlag: e.shapeFlag,
		patchFlag: t && e.type !== V ? o === -1 ? 16 : o | 16 : o,
		dynamicProps: e.dynamicProps,
		dynamicChildren: e.dynamicChildren,
		appContext: e.appContext,
		dirs: e.dirs,
		transition: c,
		component: e.component,
		suspense: e.suspense,
		ssContent: e.ssContent && wa(e.ssContent),
		ssFallback: e.ssFallback && wa(e.ssFallback),
		placeholder: e.placeholder,
		el: e.el,
		anchor: e.anchor,
		ctx: e.ctx,
		ce: e.ce
	};
	return c && r && hr(u, c.clone(u)), u;
}
function J(e = " ", t = 0) {
	return q(ua, null, e, t);
}
function Y(e = "", t = !1) {
	return t ? (U(), G(H, null, e)) : q(H, null, e);
}
function Ta(e) {
	return e == null || typeof e == "boolean" ? q(H) : p(e) ? q(V, null, e.slice()) : va(e) ? Ea(e) : q(ua, null, String(e));
}
function Ea(e) {
	return e.el === null && e.patchFlag !== -1 || e.memo ? e : wa(e);
}
function Da(e, t) {
	let n = 0, { shapeFlag: r } = e;
	if (t == null) t = null;
	else if (p(t)) n = 16;
	else if (typeof t == "object") if (r & 65) {
		let n = t.default;
		n && (n._c && (n._d = !1), Da(e, n()), n._c && (n._d = !0));
		return;
	} else {
		n = 32;
		let r = t._;
		!r && !Fi(t) ? t._ctx = R : r === 3 && R && (R.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
	}
	else _(t) ? (t = {
		default: t,
		_ctx: R
	}, n = 32) : (t = String(t), r & 64 ? (n = 16, t = [J(t)]) : n = 8);
	e.children = t, e.shapeFlag |= n;
}
function Oa(...e) {
	let t = {};
	for (let n = 0; n < e.length; n++) {
		let r = e[n];
		for (let e in r) if (e === "class") t.class !== r.class && (t.class = k([t.class, r.class]));
		else if (e === "style") t.style = pe([t.style, r.style]);
		else if (s(e)) {
			let n = t[e], i = r[e];
			i && n !== i && !(p(n) && n.includes(i)) ? t[e] = n ? [].concat(n, i) : i : i == null && n == null && !c(e) && (t[e] = i);
		} else e !== "" && (t[e] = r[e]);
	}
	return t;
}
function ka(e, t, n, r = null) {
	un(e, t, 7, [n, r]);
}
var Aa = gi(), ja = 0;
function Ma(e, t, n) {
	let i = e.type, a = (t ? t.appContext : e.appContext) || Aa, o = {
		uid: ja++,
		vnode: e,
		type: i,
		parent: t,
		appContext: a,
		root: null,
		next: null,
		subTree: null,
		effect: null,
		update: null,
		job: null,
		scope: new De(!0),
		render: null,
		proxy: null,
		exposed: null,
		exposeProxy: null,
		withProxy: null,
		provides: t ? t.provides : Object.create(a.provides),
		ids: t ? t.ids : [
			"",
			0,
			0
		],
		accessCache: null,
		renderCache: [],
		components: null,
		directives: null,
		propsOptions: Vi(i, a),
		emitsOptions: wi(i, a),
		emit: null,
		emitted: null,
		propsDefaults: r,
		inheritAttrs: i.inheritAttrs,
		ctx: r,
		data: r,
		props: r,
		attrs: r,
		slots: r,
		refs: r,
		setupState: r,
		setupContext: null,
		suspense: n,
		suspenseId: n ? n.pendingId : 0,
		asyncDep: null,
		asyncResolved: !1,
		isMounted: !1,
		isUnmounted: !1,
		isDeactivated: !1,
		bc: null,
		c: null,
		bm: null,
		m: null,
		bu: null,
		u: null,
		um: null,
		bum: null,
		da: null,
		a: null,
		rtg: null,
		rtc: null,
		ec: null,
		sp: null
	};
	return o.ctx = { _: o }, o.root = t ? t.root : o, o.emit = Si.bind(null, o), e.ce && e.ce(o), o;
}
var X = null, Na = () => X || R, Pa, Fa;
{
	let e = fe(), t = (t, n) => {
		let r;
		return (r = e[t]) || (r = e[t] = []), r.push(n), (e) => {
			r.length > 1 ? r.forEach((t) => t(e)) : r[0](e);
		};
	};
	Pa = t("__VUE_INSTANCE_SETTERS__", (e) => X = e), Fa = t("__VUE_SSR_SETTERS__", (e) => za = e);
}
var Ia = (e) => {
	let t = X;
	return Pa(e), e.scope.on(), () => {
		e.scope.off(), Pa(t);
	};
}, La = () => {
	X && X.scope.off(), Pa(null);
};
function Ra(e) {
	return e.vnode.shapeFlag & 4;
}
var za = !1;
function Ba(e, t = !1, n = !1) {
	t && Fa(t);
	let { props: r, children: i } = e.vnode, a = Ra(e);
	Ii(e, r, a, t), Yi(e, i, n || t);
	let o = a ? Va(e, t) : void 0;
	return t && Fa(!1), o;
}
function Va(e, t) {
	let n = e.type;
	e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, Qr);
	let { setup: r } = n;
	if (r) {
		Ge();
		let n = e.setupContext = r.length > 1 ? qa(e) : null, i = Ia(e), a = ln(r, e, 0, [e.props, n]), o = x(a);
		if (Ke(), i(), (o || e.sp) && !wr(e) && yr(e), o) {
			if (a.then(La, La), t) return a.then((n) => {
				Ha(e, n, t);
			}).catch((t) => {
				dn(t, e, 0);
			});
			e.asyncDep = a;
		} else Ha(e, a, t);
	} else Ga(e, t);
}
function Ha(e, t, n) {
	_(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : b(t) && (e.setupState = Zt(t)), Ga(e, n);
}
var Ua, Wa;
function Ga(e, t, n) {
	let r = e.type;
	if (!e.render) {
		if (!t && Ua && !r.render) {
			let t = r.template || oi(e).template;
			if (t) {
				let { isCustomElement: n, compilerOptions: i } = e.appContext.config, { delimiters: a, compilerOptions: o } = r;
				r.render = Ua(t, l(l({
					isCustomElement: n,
					delimiters: a
				}, i), o));
			}
		}
		e.render = r.render || a, Wa && Wa(e);
	}
	{
		let t = Ia(e);
		Ge();
		try {
			ni(e);
		} finally {
			Ke(), t();
		}
	}
}
var Ka = { get(e, t) {
	return N(e, "get", ""), e[t];
} };
function qa(e) {
	return {
		attrs: new Proxy(e.attrs, Ka),
		slots: e.slots,
		emit: e.emit,
		expose: (t) => {
			e.exposed = t || {};
		}
	};
}
function Ja(e) {
	return e.exposed ? e.exposeProxy ||= new Proxy(Zt(Wt(e.exposed)), {
		get(t, n) {
			if (n in t) return t[n];
			if (n in Xr) return Xr[n](e);
		},
		has(e, t) {
			return t in e || t in Xr;
		}
	}) : e.proxy;
}
function Ya(e, t = !0) {
	return _(e) ? e.displayName || e.name : e.name || t && e.__name;
}
function Xa(e) {
	return _(e) && "__vccOpts" in e;
}
var Z = (e, t) => /* @__PURE__ */ tn(e, t, za);
function Za(e, t, n) {
	try {
		ga(-1);
		let r = arguments.length;
		return r === 2 ? b(t) && !p(t) ? va(t) ? q(e, null, [t]) : q(e, t) : q(e, null, t) : (r > 3 ? n = Array.prototype.slice.call(arguments, 2) : r === 3 && va(n) && (n = [n]), q(e, t, n));
	} finally {
		ga(1);
	}
}
var Qa = "3.5.38", $a = void 0, eo = typeof window < "u" && window.trustedTypes;
if (eo) try {
	$a = /* @__PURE__ */ eo.createPolicy("vue", { createHTML: (e) => e });
} catch {}
var to = $a ? (e) => $a.createHTML(e) : (e) => e, no = "http://www.w3.org/2000/svg", ro = "http://www.w3.org/1998/Math/MathML", io = typeof document < "u" ? document : null, ao = io && /* @__PURE__ */ io.createElement("template"), oo = {
	insert: (e, t, n) => {
		t.insertBefore(e, n || null);
	},
	remove: (e) => {
		let t = e.parentNode;
		t && t.removeChild(e);
	},
	createElement: (e, t, n, r) => {
		let i = t === "svg" ? io.createElementNS(no, e) : t === "mathml" ? io.createElementNS(ro, e) : n ? io.createElement(e, { is: n }) : io.createElement(e);
		return e === "select" && r && r.multiple != null && i.setAttribute("multiple", r.multiple), i;
	},
	createText: (e) => io.createTextNode(e),
	createComment: (e) => io.createComment(e),
	setText: (e, t) => {
		e.nodeValue = t;
	},
	setElementText: (e, t) => {
		e.textContent = t;
	},
	parentNode: (e) => e.parentNode,
	nextSibling: (e) => e.nextSibling,
	querySelector: (e) => io.querySelector(e),
	setScopeId(e, t) {
		e.setAttribute(t, "");
	},
	insertStaticContent(e, t, n, r, i, a) {
		let o = n ? n.previousSibling : t.lastChild;
		if (i && (i === a || i.nextSibling)) for (; t.insertBefore(i.cloneNode(!0), n), !(i === a || !(i = i.nextSibling)););
		else {
			ao.innerHTML = to(r === "svg" ? `<svg>${e}</svg>` : r === "mathml" ? `<math>${e}</math>` : e);
			let i = ao.content;
			if (r === "svg" || r === "mathml") {
				let e = i.firstChild;
				for (; e.firstChild;) i.appendChild(e.firstChild);
				i.removeChild(e);
			}
			t.insertBefore(i, n);
		}
		return [o ? o.nextSibling : t.firstChild, n ? n.previousSibling : t.lastChild];
	}
}, so = "transition", co = "animation", lo = /* @__PURE__ */ Symbol("_vtc"), uo = {
	name: String,
	type: String,
	css: {
		type: Boolean,
		default: !0
	},
	duration: [
		String,
		Number,
		Object
	],
	enterFromClass: String,
	enterActiveClass: String,
	enterToClass: String,
	appearFromClass: String,
	appearActiveClass: String,
	appearToClass: String,
	leaveFromClass: String,
	leaveActiveClass: String,
	leaveToClass: String
}, fo = /* @__PURE__ */ l({}, or, uo), po = /* @__PURE__ */ ((e) => (e.displayName = "Transition", e.props = fo, e))((e, { slots: t }) => Za(ur, go(e), t)), mo = (e, t = []) => {
	p(e) ? e.forEach((e) => e(...t)) : e && e(...t);
}, ho = (e) => e ? p(e) ? e.some((e) => e.length > 1) : e.length > 1 : !1;
function go(e) {
	let t = {};
	for (let n in e) n in uo || (t[n] = e[n]);
	if (e.css === !1) return t;
	let { name: n = "v", type: r, duration: i, enterFromClass: a = `${n}-enter-from`, enterActiveClass: o = `${n}-enter-active`, enterToClass: s = `${n}-enter-to`, appearFromClass: c = a, appearActiveClass: u = o, appearToClass: d = s, leaveFromClass: f = `${n}-leave-from`, leaveActiveClass: p = `${n}-leave-active`, leaveToClass: m = `${n}-leave-to` } = e, h = _o(i), g = h && h[0], _ = h && h[1], { onBeforeEnter: v, onEnter: y, onEnterCancelled: b, onLeave: x, onLeaveCancelled: S, onBeforeAppear: C = v, onAppear: w = y, onAppearCancelled: ee = b } = t, T = (e, t, n, r) => {
		e._enterCancelled = r, bo(e, t ? d : s), bo(e, t ? u : o), n && n();
	}, te = (e, t) => {
		e._isLeaving = !1, bo(e, f), bo(e, m), bo(e, p), t && t();
	}, ne = (e) => (t, n) => {
		let i = e ? w : y, o = () => T(t, e, n);
		mo(i, [t, o]), xo(() => {
			bo(t, e ? c : a), yo(t, e ? d : s), ho(i) || Co(t, r, g, o);
		});
	};
	return l(t, {
		onBeforeEnter(e) {
			mo(v, [e]), yo(e, a), yo(e, o);
		},
		onBeforeAppear(e) {
			mo(C, [e]), yo(e, c), yo(e, u);
		},
		onEnter: ne(!1),
		onAppear: ne(!0),
		onLeave(e, t) {
			e._isLeaving = !0;
			let n = () => te(e, t);
			yo(e, f), e._enterCancelled ? (yo(e, p), Do(e)) : (Do(e), yo(e, p)), xo(() => {
				e._isLeaving && (bo(e, f), yo(e, m), ho(x) || Co(e, r, _, n));
			}), mo(x, [e, n]);
		},
		onEnterCancelled(e) {
			T(e, !1, void 0, !0), mo(b, [e]);
		},
		onAppearCancelled(e) {
			T(e, !0, void 0, !0), mo(ee, [e]);
		},
		onLeaveCancelled(e) {
			te(e), mo(S, [e]);
		}
	});
}
function _o(e) {
	if (e == null) return null;
	if (b(e)) return [vo(e.enter), vo(e.leave)];
	{
		let t = vo(e);
		return [t, t];
	}
}
function vo(e) {
	return ue(e);
}
function yo(e, t) {
	t.split(/\s+/).forEach((t) => t && e.classList.add(t)), (e[lo] || (e[lo] = /* @__PURE__ */ new Set())).add(t);
}
function bo(e, t) {
	t.split(/\s+/).forEach((t) => t && e.classList.remove(t));
	let n = e[lo];
	n && (n.delete(t), n.size || (e[lo] = void 0));
}
function xo(e) {
	requestAnimationFrame(() => {
		requestAnimationFrame(e);
	});
}
var So = 0;
function Co(e, t, n, r) {
	let i = e._endId = ++So, a = () => {
		i === e._endId && r();
	};
	if (n != null) return setTimeout(a, n);
	let { type: o, timeout: s, propCount: c } = wo(e, t);
	if (!o) return r();
	let l = o + "end", u = 0, d = () => {
		e.removeEventListener(l, f), a();
	}, f = (t) => {
		t.target === e && ++u >= c && d();
	};
	setTimeout(() => {
		u < c && d();
	}, s + 1), e.addEventListener(l, f);
}
function wo(e, t) {
	let n = window.getComputedStyle(e), r = (e) => (n[e] || "").split(", "), i = r(`${so}Delay`), a = r(`${so}Duration`), o = To(i, a), s = r(`${co}Delay`), c = r(`${co}Duration`), l = To(s, c), u = null, d = 0, f = 0;
	t === so ? o > 0 && (u = so, d = o, f = a.length) : t === co ? l > 0 && (u = co, d = l, f = c.length) : (d = Math.max(o, l), u = d > 0 ? o > l ? so : co : null, f = u ? u === so ? a.length : c.length : 0);
	let p = u === so && /\b(?:transform|all)(?:,|$)/.test(r(`${so}Property`).toString());
	return {
		type: u,
		timeout: d,
		propCount: f,
		hasTransform: p
	};
}
function To(e, t) {
	for (; e.length < t.length;) e = e.concat(e);
	return Math.max(...t.map((t, n) => Eo(t) + Eo(e[n])));
}
function Eo(e) {
	return e === "auto" ? 0 : Number(e.slice(0, -1).replace(",", ".")) * 1e3;
}
function Do(e) {
	return (e ? e.ownerDocument : document).body.offsetHeight;
}
function Oo(e, t, n) {
	let r = e[lo];
	r && (t = (t ? [t, ...r] : [...r]).join(" ")), t == null ? e.removeAttribute("class") : n ? e.setAttribute("class", t) : e.className = t;
}
var ko = /* @__PURE__ */ Symbol("_vod"), Ao = /* @__PURE__ */ Symbol("_vsh"), jo = /* @__PURE__ */ Symbol(""), Mo = /(?:^|;)\s*display\s*:/;
function No(e, t, n) {
	let r = e.style, i = v(n), a = !1;
	if (n && !i) {
		if (t) if (v(t)) for (let e of t.split(";")) {
			let t = e.slice(0, e.indexOf(":")).trim();
			n[t] ?? Fo(r, t, "");
		}
		else for (let e in t) n[e] ?? Fo(r, e, "");
		for (let i in n) {
			i === "display" && (a = !0);
			let o = n[i];
			o == null ? Fo(r, i, "") : zo(e, i, !v(t) && t ? t[i] : void 0, o) || Fo(r, i, o);
		}
	} else if (i) {
		if (t !== n) {
			let e = r[jo];
			e && (n += ";" + e), r.cssText = n, a = Mo.test(n);
		}
	} else t && e.removeAttribute("style");
	ko in e && (e[ko] = a ? r.display : "", e[Ao] && (r.display = "none"));
}
var Po = /\s*!important$/;
function Fo(e, t, n) {
	if (p(n)) n.forEach((n) => Fo(e, t, n));
	else if (n ??= "", t.startsWith("--")) e.setProperty(t, n);
	else {
		let r = Ro(e, t);
		Po.test(n) ? e.setProperty(ie(r), n.replace(Po, ""), "important") : e[r] = n;
	}
}
var Io = [
	"Webkit",
	"Moz",
	"ms"
], Lo = {};
function Ro(e, t) {
	let n = Lo[t];
	if (n) return n;
	let r = D(t);
	if (r !== "filter" && r in e) return Lo[t] = r;
	r = ae(r);
	for (let n = 0; n < Io.length; n++) {
		let i = Io[n] + r;
		if (i in e) return Lo[t] = i;
	}
	return t;
}
function zo(e, t, n, r) {
	return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && v(r) && n === r;
}
var Bo = "http://www.w3.org/1999/xlink";
function Vo(e, t, n, r, i, a = ye(t)) {
	r && t.startsWith("xlink:") ? n == null ? e.removeAttributeNS(Bo, t.slice(6, t.length)) : e.setAttributeNS(Bo, t, n) : n == null || a && !be(n) ? e.removeAttribute(t) : e.setAttribute(t, a ? "" : y(n) ? String(n) : n);
}
function Ho(e, t, n, r, i) {
	if (t === "innerHTML" || t === "textContent") {
		n != null && (e[t] = t === "innerHTML" ? to(n) : n);
		return;
	}
	let a = e.tagName;
	if (t === "value" && a !== "PROGRESS" && !a.includes("-")) {
		let r = a === "OPTION" ? e.getAttribute("value") || "" : e.value, i = n == null ? e.type === "checkbox" ? "on" : "" : String(n);
		(r !== i || !("_value" in e)) && (e.value = i), n ?? e.removeAttribute(t), e._value = n;
		return;
	}
	let o = !1;
	if (n === "" || n == null) {
		let r = typeof e[t];
		r === "boolean" ? n = be(n) : n == null && r === "string" ? (n = "", o = !0) : r === "number" && (n = 0, o = !0);
	}
	try {
		e[t] = n;
	} catch {}
	o && e.removeAttribute(i || t);
}
function Uo(e, t, n, r) {
	e.addEventListener(t, n, r);
}
function Wo(e, t, n, r) {
	e.removeEventListener(t, n, r);
}
var Go = /* @__PURE__ */ Symbol("_vei");
function Ko(e, t, n, r, i = null) {
	let a = e[Go] || (e[Go] = {}), o = a[t];
	if (r && o) o.value = r;
	else {
		let [n, s] = Jo(t);
		r ? Uo(e, n, a[t] = Qo(r, i), s) : o && (Wo(e, n, o, s), a[t] = void 0);
	}
}
var qo = /(?:Once|Passive|Capture)$/;
function Jo(e) {
	let t;
	if (qo.test(e)) {
		t = {};
		let n;
		for (; n = e.match(qo);) e = e.slice(0, e.length - n[0].length), t[n[0].toLowerCase()] = !0;
	}
	return [e[2] === ":" ? e.slice(3) : ie(e.slice(2)), t];
}
var Yo = 0, Xo = /* @__PURE__ */ Promise.resolve(), Zo = () => Yo ||= (Xo.then(() => Yo = 0), Date.now());
function Qo(e, t) {
	let n = (e) => {
		if (!e._vts) e._vts = Date.now();
		else if (e._vts <= n.attached) return;
		let r = n.value;
		if (p(r)) {
			let n = e.stopImmediatePropagation;
			e.stopImmediatePropagation = () => {
				n.call(e), e._stopped = !0;
			};
			let i = r.slice(), a = [e];
			for (let n = 0; n < i.length && !e._stopped; n++) {
				let e = i[n];
				e && un(e, t, 5, a);
			}
		} else un(r, t, 5, [e]);
	};
	return n.value = e, n.attached = Zo(), n;
}
var $o = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, es = (e, t, n, r, i, a) => {
	let o = i === "svg";
	t === "class" ? Oo(e, r, o) : t === "style" ? No(e, n, r) : s(t) ? c(t) || Ko(e, t, n, r, a) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : ts(e, t, r, o)) ? (Ho(e, t, r), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && Vo(e, t, r, o, a, t !== "value")) : e._isVueCE && (ns(e, t) || e._def.__asyncLoader && (/[A-Z]/.test(t) || !v(r))) ? Ho(e, D(t), r, a, t) : (t === "true-value" ? e._trueValue = r : t === "false-value" && (e._falseValue = r), Vo(e, t, r, o));
};
function ts(e, t, n, r) {
	if (r) return !!(t === "innerHTML" || t === "textContent" || t in e && $o(t) && _(n));
	if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA") return !1;
	if (t === "width" || t === "height") {
		let t = e.tagName;
		if (t === "IMG" || t === "VIDEO" || t === "CANVAS" || t === "SOURCE") return !1;
	}
	return $o(t) && v(n) ? !1 : t in e;
}
function ns(e, t) {
	let n = e._def.props;
	if (!n) return !1;
	let r = D(t);
	return Array.isArray(n) ? n.some((e) => D(e) === r) : Object.keys(n).some((e) => D(e) === r);
}
var rs = (e) => {
	let t = e.props["onUpdate:modelValue"] || !1;
	return p(t) ? (e) => se(t, e) : t;
};
function is(e) {
	e.target.composing = !0;
}
function as(e) {
	let t = e.target;
	t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
var os = /* @__PURE__ */ Symbol("_assign");
function ss(e, t, n) {
	return t && (e = e.trim()), n && (e = le(e)), e;
}
var Q = {
	created(e, { modifiers: { lazy: t, trim: n, number: r } }, i) {
		e[os] = rs(i);
		let a = r || i.props && i.props.type === "number";
		Uo(e, t ? "change" : "input", (t) => {
			t.target.composing || e[os](ss(e.value, n, a));
		}), (n || a) && Uo(e, "change", () => {
			e.value = ss(e.value, n, a);
		}), t || (Uo(e, "compositionstart", is), Uo(e, "compositionend", as), Uo(e, "change", as));
	},
	mounted(e, { value: t }) {
		e.value = t ?? "";
	},
	beforeUpdate(e, { value: t, oldValue: n, modifiers: { lazy: r, trim: i, number: a } }, o) {
		if (e[os] = rs(o), e.composing) return;
		let s = (a || e.type === "number") && !/^0\d/.test(e.value) ? le(e.value) : e.value, c = t ?? "";
		if (s === c) return;
		let l = e.getRootNode();
		(l instanceof Document || l instanceof ShadowRoot) && l.activeElement === e && e.type !== "range" && (r && t === n || i && e.value.trim() === c) || (e.value = c);
	}
}, cs = {
	deep: !0,
	created(e, t, n) {
		e[os] = rs(n), Uo(e, "change", () => {
			let t = e._modelValue, n = ps(e), r = e.checked, i = e[os];
			if (p(t)) {
				let e = Ce(t, n), a = e !== -1;
				if (r && !a) i(t.concat(n));
				else if (!r && a) {
					let n = [...t];
					n.splice(e, 1), i(n);
				}
			} else if (h(t)) {
				let e = new Set(t);
				r ? e.add(n) : e.delete(n), i(e);
			} else i(ms(e, r));
		});
	},
	mounted: ls,
	beforeUpdate(e, t, n) {
		e[os] = rs(n), ls(e, t, n);
	}
};
function ls(e, { value: t, oldValue: n }, r) {
	e._modelValue = t;
	let i;
	if (p(t)) i = Ce(t, r.props.value) > -1;
	else if (h(t)) i = t.has(r.props.value);
	else {
		if (t === n) return;
		i = Se(t, ms(e, !0));
	}
	e.checked !== i && (e.checked = i);
}
var us = {
	created(e, { value: t }, n) {
		e.checked = Se(t, n.props.value), e[os] = rs(n), Uo(e, "change", () => {
			e[os](ps(e));
		});
	},
	beforeUpdate(e, { value: t, oldValue: n }, r) {
		e[os] = rs(r), t !== n && (e.checked = Se(t, r.props.value));
	}
}, ds = {
	deep: !0,
	created(e, { value: t, modifiers: { number: n } }, r) {
		let i = h(t);
		Uo(e, "change", () => {
			let t = Array.prototype.filter.call(e.options, (e) => e.selected).map((e) => n ? le(ps(e)) : ps(e));
			e[os](e.multiple ? i ? new Set(t) : t : t[0]), e._assigning = !0, bn(() => {
				e._assigning = !1;
			});
		}), e[os] = rs(r);
	},
	mounted(e, { value: t }) {
		fs(e, t);
	},
	beforeUpdate(e, t, n) {
		e[os] = rs(n);
	},
	updated(e, { value: t }) {
		e._assigning || fs(e, t);
	}
};
function fs(e, t) {
	let n = e.multiple, r = p(t);
	if (!(n && !r && !h(t))) {
		for (let i = 0, a = e.options.length; i < a; i++) {
			let a = e.options[i], o = ps(a);
			if (n) if (r) {
				let e = typeof o;
				e === "string" || e === "number" ? a.selected = t.some((e) => String(e) === String(o)) : a.selected = Ce(t, o) > -1;
			} else a.selected = t.has(o);
			else if (Se(ps(a), t)) {
				e.selectedIndex !== i && (e.selectedIndex = i);
				return;
			}
		}
		!n && e.selectedIndex !== -1 && (e.selectedIndex = -1);
	}
}
function ps(e) {
	return "_value" in e ? e._value : e.value;
}
function ms(e, t) {
	let n = t ? "_trueValue" : "_falseValue";
	return n in e ? e[n] : t;
}
var hs = {
	created(e, t, n) {
		_s(e, t, n, null, "created");
	},
	mounted(e, t, n) {
		_s(e, t, n, null, "mounted");
	},
	beforeUpdate(e, t, n, r) {
		_s(e, t, n, r, "beforeUpdate");
	},
	updated(e, t, n, r) {
		_s(e, t, n, r, "updated");
	}
};
function gs(e, t) {
	switch (e) {
		case "SELECT": return ds;
		case "TEXTAREA": return Q;
		default: switch (t) {
			case "checkbox": return cs;
			case "radio": return us;
			default: return Q;
		}
	}
}
function _s(e, t, n, r, i) {
	let a = gs(e.tagName, n.props && n.props.type)[i];
	a && a(e, t, n, r);
}
var vs = [
	"ctrl",
	"shift",
	"alt",
	"meta"
], ys = {
	stop: (e) => e.stopPropagation(),
	prevent: (e) => e.preventDefault(),
	self: (e) => e.target !== e.currentTarget,
	ctrl: (e) => !e.ctrlKey,
	shift: (e) => !e.shiftKey,
	alt: (e) => !e.altKey,
	meta: (e) => !e.metaKey,
	left: (e) => "button" in e && e.button !== 0,
	middle: (e) => "button" in e && e.button !== 1,
	right: (e) => "button" in e && e.button !== 2,
	exact: (e, t) => vs.some((n) => e[`${n}Key`] && !t.includes(n))
}, bs = (e, t) => {
	if (!e) return e;
	let n = e._withMods ||= {}, r = t.join(".");
	return n[r] || (n[r] = ((n, ...r) => {
		for (let e = 0; e < t.length; e++) {
			let r = ys[t[e]];
			if (r && r(n, t)) return;
		}
		return e(n, ...r);
	}));
}, xs = {
	esc: "escape",
	space: " ",
	up: "arrow-up",
	left: "arrow-left",
	right: "arrow-right",
	down: "arrow-down",
	delete: "backspace"
}, Ss = (e, t) => {
	let n = e._withKeys ||= {}, r = t.join(".");
	return n[r] || (n[r] = ((n) => {
		if (!("key" in n)) return;
		let r = ie(n.key);
		if (t.some((e) => e === r || xs[e] === r)) return e(n);
	}));
}, Cs = /* @__PURE__ */ l({ patchProp: es }, oo), ws;
function Ts() {
	return ws ||= Qi(Cs);
}
var Es = ((...e) => {
	let t = Ts().createApp(...e), { mount: n } = t;
	return t.mount = (e) => {
		let r = Os(e);
		if (!r) return;
		let i = t._component;
		!_(i) && !i.render && !i.template && (i.template = r.innerHTML), r.nodeType === 1 && (r.textContent = "");
		let a = n(r, !1, Ds(r));
		return r instanceof Element && (r.removeAttribute("v-cloak"), r.setAttribute("data-v-app", "")), a;
	}, t;
});
function Ds(e) {
	if (e instanceof SVGElement) return "svg";
	if (typeof MathMLElement == "function" && e instanceof MathMLElement) return "mathml";
}
function Os(e) {
	return v(e) ? document.querySelector(e) : e;
}
//#endregion
//#region node_modules/lucide-vue-next/dist/esm/shared/src/utils/hasA11yProp.js
var ks = (e) => {
	for (let t in e) if (t.startsWith("aria-") || t === "role" || t === "title") return !0;
	return !1;
}, As = (e) => e === "", js = (...e) => e.filter((e, t, n) => !!e && e.trim() !== "" && n.indexOf(e) === t).join(" ").trim(), Ms = (e) => e.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase(), Ns = (e) => e.replace(/^([A-Z])|[\s-_]+(\w)/g, (e, t, n) => n ? n.toUpperCase() : t.toLowerCase()), Ps = (e) => {
	let t = Ns(e);
	return t.charAt(0).toUpperCase() + t.slice(1);
}, Fs = {
	xmlns: "http://www.w3.org/2000/svg",
	width: 24,
	height: 24,
	viewBox: "0 0 24 24",
	fill: "none",
	stroke: "currentColor",
	"stroke-width": 2,
	"stroke-linecap": "round",
	"stroke-linejoin": "round"
}, Is = ({ name: e, iconNode: t, absoluteStrokeWidth: n, "absolute-stroke-width": r, strokeWidth: i, "stroke-width": a, size: o = Fs.width, color: s = Fs.stroke, ...c }, { slots: l }) => Za("svg", {
	...Fs,
	...c,
	width: o,
	height: o,
	stroke: s,
	"stroke-width": As(n) || As(r) || n === !0 || r === !0 ? Number(i || a || Fs["stroke-width"]) * 24 / Number(o) : i || a || Fs["stroke-width"],
	class: js("lucide", c.class, ...e ? [`lucide-${Ms(Ps(e))}-icon`, `lucide-${Ms(e)}`] : ["lucide-icon"]),
	...!l.default && !ks(c) && { "aria-hidden": "true" }
}, [...t.map((e) => Za(...e)), ...l.default ? [l.default()] : []]), $ = (e, t) => (n, { slots: r, attrs: i }) => Za(Is, {
	...i,
	...n,
	iconNode: t,
	name: e
}, r), Ls = $("activity", [["path", {
	d: "M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2",
	key: "169zse"
}]]), Rs = $("arrow-down-to-line", [
	["path", {
		d: "M12 17V3",
		key: "1cwfxf"
	}],
	["path", {
		d: "m6 11 6 6 6-6",
		key: "12ii2o"
	}],
	["path", {
		d: "M19 21H5",
		key: "150jfl"
	}]
]), zs = $("arrow-down", [["path", {
	d: "M12 5v14",
	key: "s699le"
}], ["path", {
	d: "m19 12-7 7-7-7",
	key: "1idqje"
}]]), Bs = $("arrow-left-right", [
	["path", {
		d: "M8 3 4 7l4 4",
		key: "9rb6wj"
	}],
	["path", {
		d: "M4 7h16",
		key: "6tx8e3"
	}],
	["path", {
		d: "m16 21 4-4-4-4",
		key: "siv7j2"
	}],
	["path", {
		d: "M20 17H4",
		key: "h6l3hr"
	}]
]), Vs = $("arrow-up-right", [["path", {
	d: "M7 7h10v10",
	key: "1tivn9"
}], ["path", {
	d: "M7 17 17 7",
	key: "1vkiza"
}]]), Hs = $("arrow-up", [["path", {
	d: "m5 12 7-7 7 7",
	key: "hav0vg"
}], ["path", {
	d: "M12 19V5",
	key: "x0mq9r"
}]]), Us = $("check", [["path", {
	d: "M20 6 9 17l-5-5",
	key: "1gmf2c"
}]]), Ws = $("chevron-down", [["path", {
	d: "m6 9 6 6 6-6",
	key: "qrunsl"
}]]), Gs = $("chevron-right", [["path", {
	d: "m9 18 6-6-6-6",
	key: "mthhwq"
}]]), Ks = $("chevron-up", [["path", {
	d: "m18 15-6-6-6 6",
	key: "153udz"
}]]), qs = $("clock", [["circle", {
	cx: "12",
	cy: "12",
	r: "10",
	key: "1mglay"
}], ["path", {
	d: "M12 6v6l4 2",
	key: "mmk7yg"
}]]), Js = $("database", [
	["ellipse", {
		cx: "12",
		cy: "5",
		rx: "9",
		ry: "3",
		key: "msslwz"
	}],
	["path", {
		d: "M3 5V19A9 3 0 0 0 21 19V5",
		key: "1wlel7"
	}],
	["path", {
		d: "M3 12A9 3 0 0 0 21 12",
		key: "mv7ke4"
	}]
]), Ys = $("download", [
	["path", {
		d: "M12 15V3",
		key: "m9g1x1"
	}],
	["path", {
		d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4",
		key: "ih7n3h"
	}],
	["path", {
		d: "m7 10 5 5 5-5",
		key: "brsn70"
	}]
]), Xs = $("eye-off", [
	["path", {
		d: "M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49",
		key: "ct8e1f"
	}],
	["path", {
		d: "M14.084 14.158a3 3 0 0 1-4.242-4.242",
		key: "151rxh"
	}],
	["path", {
		d: "M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143",
		key: "13bj9a"
	}],
	["path", {
		d: "m2 2 20 20",
		key: "1ooewy"
	}]
]), Zs = $("eye", [["path", {
	d: "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0",
	key: "1nclc0"
}], ["circle", {
	cx: "12",
	cy: "12",
	r: "3",
	key: "1v7zrd"
}]]), Qs = $("file-down", [
	["path", {
		d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
		key: "1oefj6"
	}],
	["path", {
		d: "M14 2v5a1 1 0 0 0 1 1h5",
		key: "wfsgrz"
	}],
	["path", {
		d: "M12 18v-6",
		key: "17g6i2"
	}],
	["path", {
		d: "m9 15 3 3 3-3",
		key: "1npd3o"
	}]
]), $s = $("file-up", [
	["path", {
		d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
		key: "1oefj6"
	}],
	["path", {
		d: "M14 2v5a1 1 0 0 0 1 1h5",
		key: "wfsgrz"
	}],
	["path", {
		d: "M12 12v6",
		key: "3ahymv"
	}],
	["path", {
		d: "m15 15-3-3-3 3",
		key: "15xj92"
	}]
]), ec = $("gauge", [["path", {
	d: "m12 14 4-4",
	key: "9kzdfg"
}], ["path", {
	d: "M3.34 19a10 10 0 1 1 17.32 0",
	key: "19p75a"
}]]), tc = $("globe", [
	["circle", {
		cx: "12",
		cy: "12",
		r: "10",
		key: "1mglay"
	}],
	["path", {
		d: "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20",
		key: "13o1zl"
	}],
	["path", {
		d: "M2 12h20",
		key: "9i4pu4"
	}]
]), nc = $("house", [["path", {
	d: "M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8",
	key: "5wwlr5"
}], ["path", {
	d: "M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
	key: "r6nss1"
}]]), rc = $("link", [["path", {
	d: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71",
	key: "1cjeqo"
}], ["path", {
	d: "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71",
	key: "19qd67"
}]]), ic = $("monitor", [
	["rect", {
		width: "20",
		height: "14",
		x: "2",
		y: "3",
		rx: "2",
		key: "48i651"
	}],
	["line", {
		x1: "8",
		x2: "16",
		y1: "21",
		y2: "21",
		key: "1svkeh"
	}],
	["line", {
		x1: "12",
		x2: "12",
		y1: "17",
		y2: "21",
		key: "vw1qmm"
	}]
]), ac = $("network", [
	["rect", {
		x: "16",
		y: "16",
		width: "6",
		height: "6",
		rx: "1",
		key: "4q2zg0"
	}],
	["rect", {
		x: "2",
		y: "16",
		width: "6",
		height: "6",
		rx: "1",
		key: "8cvhb9"
	}],
	["rect", {
		x: "9",
		y: "2",
		width: "6",
		height: "6",
		rx: "1",
		key: "1egb70"
	}],
	["path", {
		d: "M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3",
		key: "1jsf9p"
	}],
	["path", {
		d: "M12 12V8",
		key: "2874zd"
	}]
]), oc = $("pause", [["rect", {
	x: "14",
	y: "3",
	width: "5",
	height: "18",
	rx: "1",
	key: "kaeet6"
}], ["rect", {
	x: "5",
	y: "3",
	width: "5",
	height: "18",
	rx: "1",
	key: "1wsw3u"
}]]), sc = $("play", [["path", {
	d: "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z",
	key: "10ikf1"
}]]), cc = $("plus", [["path", {
	d: "M5 12h14",
	key: "1ays0h"
}], ["path", {
	d: "M12 5v14",
	key: "s699le"
}]]), lc = $("power", [["path", {
	d: "M12 2v10",
	key: "mnfbl"
}], ["path", {
	d: "M18.4 6.6a9 9 0 1 1-12.77.04",
	key: "obofu9"
}]]), uc = $("radio", [
	["path", {
		d: "M16.247 7.761a6 6 0 0 1 0 8.478",
		key: "1fwjs5"
	}],
	["path", {
		d: "M19.075 4.933a10 10 0 0 1 0 14.134",
		key: "ehdyv1"
	}],
	["path", {
		d: "M4.925 19.067a10 10 0 0 1 0-14.134",
		key: "1q22gi"
	}],
	["path", {
		d: "M7.753 16.239a6 6 0 0 1 0-8.478",
		key: "r2q7qm"
	}],
	["circle", {
		cx: "12",
		cy: "12",
		r: "2",
		key: "1c9p78"
	}]
]), dc = $("refresh-cw", [
	["path", {
		d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8",
		key: "v9h5vc"
	}],
	["path", {
		d: "M21 3v5h-5",
		key: "1q7to0"
	}],
	["path", {
		d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16",
		key: "3uifl3"
	}],
	["path", {
		d: "M8 16H3v5",
		key: "1cv678"
	}]
]), fc = $("search", [["path", {
	d: "m21 21-4.34-4.34",
	key: "14j7rj"
}], ["circle", {
	cx: "11",
	cy: "11",
	r: "8",
	key: "4ej97u"
}]]), pc = $("settings-2", [
	["path", {
		d: "M14 17H5",
		key: "gfn3mx"
	}],
	["path", {
		d: "M19 7h-9",
		key: "6i9tg"
	}],
	["circle", {
		cx: "17",
		cy: "17",
		r: "3",
		key: "18b49y"
	}],
	["circle", {
		cx: "7",
		cy: "7",
		r: "3",
		key: "dfmy0x"
	}]
]), mc = $("shield-check", [["path", {
	d: "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",
	key: "oel41y"
}], ["path", {
	d: "m9 12 2 2 4-4",
	key: "dzmm74"
}]]), hc = $("shield-off", [
	["path", {
		d: "m2 2 20 20",
		key: "1ooewy"
	}],
	["path", {
		d: "M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.67 8.94a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71",
		key: "1jlk70"
	}],
	["path", {
		d: "M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264",
		key: "18rp1v"
	}]
]), gc = $("sliders-horizontal", [
	["path", {
		d: "M10 5H3",
		key: "1qgfaw"
	}],
	["path", {
		d: "M12 19H3",
		key: "yhmn1j"
	}],
	["path", {
		d: "M14 3v4",
		key: "1sua03"
	}],
	["path", {
		d: "M16 17v4",
		key: "1q0r14"
	}],
	["path", {
		d: "M21 12h-9",
		key: "1o4lsq"
	}],
	["path", {
		d: "M21 19h-5",
		key: "1rlt1p"
	}],
	["path", {
		d: "M21 5h-7",
		key: "1oszz2"
	}],
	["path", {
		d: "M8 10v4",
		key: "tgpxqk"
	}],
	["path", {
		d: "M8 12H3",
		key: "a7s4jb"
	}]
]), _c = $("undo-2", [["path", {
	d: "M9 14 4 9l5-5",
	key: "102s5s"
}], ["path", {
	d: "M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11",
	key: "f3b9sd"
}]]), vc = $("x", [["path", {
	d: "M18 6 6 18",
	key: "1bl5f8"
}], ["path", {
	d: "m6 6 12 12",
	key: "d8bk6v"
}]]), yc = $("zap", [["path", {
	d: "M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z",
	key: "1xq2db"
}]]), bc = (t) => t == null ? "—" : `${e(t)}/s`, xc = (e) => ({
	active: "下载中",
	waiting: "等待中",
	paused: "已暂停",
	complete: "已完成",
	removed: "已取消",
	error: "下载失败",
	recoverable: "待恢复"
})[e] || "等待中", Sc = (e) => e ? new Date(e).toLocaleString("zh-CN", {
	month: "2-digit",
	day: "2-digit",
	hour: "2-digit",
	minute: "2-digit"
}) : "刚刚", Cc = (e) => e === "DIRECT" ? "直接连接" : e === "REJECT" ? "阻止连接" : e || "尚未选择线路";
function wc(e, t, n = 0) {
	let r = e?.[t];
	return !r || !Array.isArray(r.all) || !r.now || n > 4 ? t : wc(e, r.now, n + 1);
}
function Tc(e) {
	let t = e?.proxies;
	if (!t) return "";
	let n = Object.entries(t).filter(([, e]) => Array.isArray(e.all) && e.now), r = n.find(([e]) => e === "GLOBAL") || n.find(([, e]) => e.type === "Selector") || n[0];
	return r ? wc(t, r[1].now) : "";
}
function Ec(e) {
	let n = /* @__PURE__ */ qt(null), r = /* @__PURE__ */ I(null), i = /* @__PURE__ */ I([]), a = Z(() => n.value?.downloads || []), o = /* @__PURE__ */ I(null), s = /* @__PURE__ */ I(""), c = /* @__PURE__ */ I(""), l = /* @__PURE__ */ I(""), u = /* @__PURE__ */ I(""), d = /* @__PURE__ */ I(!1), f = !1, p, m = async (t, n = {}) => {
		if (f || e.signal?.aborted) throw Error("页面已关闭");
		let r = await e.rpc(`easynet.${t}`, n);
		if (f || e.signal?.aborted) throw Error("页面已关闭");
		return r;
	};
	async function h(e, t = {}) {
		try {
			return await m(e, t);
		} catch (e) {
			return f || (c.value = e instanceof Error ? e.message : String(e)), null;
		}
	}
	async function g() {
		if (!n.value?.proxy?.running) {
			r.value = null;
			return;
		}
		return p || (p = m("proxy.inspect").then((e) => {
			r.value = e;
		}).catch((e) => {
			f || (c.value = String(e));
		}).finally(() => {
			p = void 0;
		}), p);
	}
	async function _() {
		let e = await h("system.inspect", { kind: "proxy" });
		e && (o.value = e);
	}
	async function v() {
		await t.refresh();
	}
	async function y(e, n = {}, r = "") {
		if (s.value) return null;
		s.value = e, c.value = "", l.value = "";
		try {
			let i = await m(e, n);
			return l.value = i.cancelled ? "已取消操作" : r, await t.refresh(), i;
		} catch (e) {
			return f || (c.value = e instanceof Error ? e.message : String(e)), null;
		} finally {
			f || (s.value = "");
		}
	}
	async function b() {
		d.value = !1;
		let e = n.value?.proxy?.running;
		await y(e ? "proxy.stop" : "proxy.start", {}, e ? "代理已关闭" : "代理已开启") && (await g(), await _());
	}
	let x = Z(() => (n.value?.transactions || []).find((e) => e.request?.kind === "proxy" && e.status === "applied")), S = Z(() => !!(n.value?.accelerator?.running && o.value?.enabled === 1 && o.value?.server === `127.0.0.1:${n.value.accelerator.port}`)), C = Z(() => o.value !== null);
	async function w() {
		if (!s.value) {
			if (S.value) {
				if (!x.value) {
					c.value = "当前系统代理不是由这里设置的，请在系统设置中关闭";
					return;
				}
				let e = await y("system.restore", { id: x.value.id }, "已恢复原来的系统代理");
				if (!e || e.cancelled) return;
				let t = await y("accelerator.stop", {}, "");
				if (!t || t.cancelled) return;
				d.value && (d.value = !1, await y("proxy.stop", {}, ""), await g());
			} else {
				if (n.value?.proxy?.config_saved && !n.value?.proxy?.running) {
					let e = await y("proxy.start", {}, "");
					e && !e.cancelled && (d.value = !0, await g());
				}
				let e = await y("accelerator.start", {}, ""), r = Number(e?.port || 0);
				if (!r) return;
				let i = !!n.value?.proxy?.running, a = await y("system.apply", {
					kind: "proxy",
					server: `127.0.0.1:${r}`
				}, i ? "本机加速已开启，线路兜底已就绪" : "本机加速已开启");
				if (!a || a.cancelled) {
					let e = c.value;
					await y("accelerator.stop", {}, ""), d.value && (d.value = !1, await y("proxy.stop", {}, ""), await g()), e ? c.value = e : l.value = "已取消操作", await _(), await t.refresh();
					return;
				}
			}
			await _(), await t.refresh();
		}
	}
	async function ee(e) {
		n.value?.proxy?.running && await y("proxy.mode", { mode: e }, "连接模式已更新") && await g();
	}
	async function T(e, t) {
		await y("proxy.select", {
			group: e,
			name: t
		}, `已切换到 ${t}`) && await g();
	}
	async function te(e) {
		let t = await y("proxy.optimize", { group: e });
		return t ? (t.selected ? (l.value = `已自动选择 ${t.selected}${t.delay ? `（${t.delay} ms）` : ""}`, await g()) : l.value = "没有可用线路，已保留当前选择", t) : null;
	}
	async function ne(e, t = "basic") {
		let n = e.trim();
		try {
			n.includes("://") && (n = new URL(n).hostname);
		} catch {
			return c.value = "请输入正确的网址或域名", null;
		}
		return y("diagnose", {
			target: n,
			port: 443,
			kind: t
		});
	}
	let E = t.subscribe({
		rpc: e.rpc,
		signal: e.signal,
		visible: () => e.visible !== !1,
		update(e, t) {
			f || (n.value = e, u.value = t || "");
		}
	}), D = e.onVisibilityChange?.(() => t.visibilityChanged()) || (() => {});
	Rn(() => n.value?.proxy?.running, () => {
		g();
	}, { immediate: !0 }), Nr(async () => {
		await Promise.all([_(), e.compact ? Promise.resolve() : h("interfaces").then((e) => {
			e && (i.value = e.interfaces || []);
		})]);
	}), Ir(() => {
		f = !0, E(), D();
	});
	async function re() {
		await Promise.all([
			t.refresh(),
			_(),
			g()
		]);
	}
	return /* @__PURE__ */ It({
		state: n,
		proxy: r,
		interfaces: i,
		tasks: a,
		systemProxy: o,
		systemProxyReady: C,
		accelerated: S,
		ownedProxy: x,
		busy: s,
		error: c,
		notice: l,
		connectionError: u,
		run: y,
		read: h,
		refresh: re,
		loadProxy: g,
		loadTasks: v,
		loadSystemProxy: _,
		toggleProxy: b,
		toggleAcceleration: w,
		setMode: ee,
		selectNode: T,
		optimizeNode: te,
		diagnose: ne
	});
}
//#endregion
//#region ../src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue
var Dc = { class: "nx-home" }, Oc = {
	class: "nx-stat-bar",
	"data-stat-bar": "",
	"aria-label": "实时网络数据"
}, kc = {
	class: "nx-stat",
	"data-stat": "download"
}, Ac = {
	class: "nx-stat",
	"data-stat": "upload"
}, jc = {
	class: "nx-stat",
	"data-stat": "total"
}, Mc = {
	class: "nx-stat",
	"data-stat": "delay"
}, Nc = { class: "nx-home-grid" }, Pc = { class: "nx-quick-head" }, Fc = { class: "nx-quick-icon" }, Ic = { class: "nx-quick-main" }, Lc = { class: "nx-quick-actions" }, Rc = ["aria-pressed", "disabled"], zc = { class: "nx-quick-head" }, Bc = { class: "nx-quick-icon" }, Vc = { class: "nx-quick-main" }, Hc = { class: "nx-quick-actions" }, Uc = ["aria-pressed", "disabled"], Wc = { class: "nx-quick-head" }, Gc = { class: "nx-quick-icon" }, Kc = { class: "nx-quick-main" }, qc = { class: "nx-quick-actions nx-quick-actions--stack" }, Jc = ["disabled"], Yc = {
	__name: "HomeView",
	props: { session: Object },
	emits: ["navigate"],
	setup(t, { emit: n }) {
		let r = t, i = n, a = /* @__PURE__ */ I(""), o = Z(() => !!r.session.accelerated), s = Z(() => Number(r.session.state?.traffic?.download || 0)), c = Z(() => Number(r.session.state?.traffic?.upload || 0)), l = Z(() => Number(r.session.state?.traffic?.received || 0) + Number(r.session.state?.traffic?.sent || 0)), u = Z(() => !!r.session.state?.proxy?.config_saved), d = Z(() => !!r.session.state?.proxy?.running), f = Z(() => Tc(r.session.proxy)), p = Z(() => f.value ? Cc(f.value) : d.value ? "正在读取线路" : "尚未连接"), m = Z(() => Number(r.session.proxy?.proxies?.[f.value]?.history?.at(-1)?.delay || 0)), h = Z(() => r.session.tasks.filter((e) => !["complete", "removed"].includes(e.status)).length), g = Z(() => r.session.tasks.reduce((e, t) => e + (Number(t.downloadSpeed) || 0), 0)), _ = Z(() => r.session.busy === "proxy.start" ? "正在准备线路…" : r.session.busy === "accelerator.start" ? "正在准备…" : r.session.busy === "system.apply" ? "正在开启…" : o.value ? "停止加速" : "一键加速"), v = Z(() => r.session.busy === "proxy.start" ? "连接中…" : r.session.busy === "proxy.stop" ? "关闭中…" : d.value ? "关闭代理" : u.value ? "开启代理" : "添加订阅");
		async function y() {
			await r.session.toggleAcceleration();
		}
		async function b() {
			if (!u.value) {
				i("navigate", "proxy");
				return;
			}
			await r.session.toggleProxy();
		}
		async function x() {
			let e = a.value.trim();
			await r.session.run("transfer.add", { url: e }, "已开始下载") && (a.value = "", await r.session.loadTasks());
		}
		return (n, r) => (U(), W("div", Dc, [K("section", Oc, [
			K("div", kc, [K("span", null, [q(L(zs), { size: 13 }), r[4] ||= J("实时下载", -1)]), K("strong", null, A(L(bc)(s.value)), 1)]),
			K("div", Ac, [K("span", null, [q(L(Hs), { size: 13 }), r[5] ||= J("实时上传", -1)]), K("strong", null, A(L(bc)(c.value)), 1)]),
			K("div", jc, [K("span", null, [q(L(Js), { size: 13 }), r[6] ||= J("累计流量", -1)]), K("strong", null, A(L(e)(l.value)), 1)]),
			K("div", Mc, [K("span", null, [q(L(ec), { size: 13 }), r[7] ||= J("线路延迟", -1)]), K("strong", null, A(m.value ? `${m.value} ms` : "—"), 1)])
		]), K("div", Nc, [
			K("section", {
				class: k(["nx-quick-card", { "is-on": o.value }]),
				"data-home-block": "acceleration"
			}, [
				K("header", Pc, [
					K("span", Fc, [q(L(yc), { size: 19 })]),
					r[8] ||= K("div", { class: "nx-quick-title" }, [K("h2", null, "加速"), K("p", null, "本机加速")], -1),
					K("span", { class: k(["nx-quick-state", { "is-live": o.value }]) }, A(o.value ? "运行中" : "未加速"), 3)
				]),
				K("div", Ic, [K("strong", null, A(o.value ? "常用站点直连" : "无需订阅"), 1), K("p", null, A(o.value ? d.value ? "本机直连 · 线路兜底已就绪" : "DoH 选路，失败时按系统解析" : "有订阅会自动准备线路兜底"), 1)]),
				K("div", Lc, [K("button", {
					class: k(["btn nx-button", o.value ? "btn--secondary" : "btn--primary"]),
					"aria-pressed": o.value,
					disabled: !!t.session.busy || !t.session.systemProxyReady,
					"data-acceleration": "",
					onClick: y
				}, [q(L(lc), { size: 15 }), J(A(_.value), 1)], 10, Rc), K("button", {
					class: "btn nx-button btn--quiet nx-quick-link",
					"data-home-open": "overview",
					onClick: r[0] ||= (e) => i("navigate", "overview")
				}, [r[9] ||= J(" 详情", -1), q(L(Vs), { size: 13 })])])
			], 2),
			K("section", {
				class: k(["nx-quick-card", { "is-on": d.value }]),
				"data-home-block": "proxy"
			}, [
				K("header", zc, [
					K("span", Bc, [q(L(tc), { size: 19 })]),
					r[10] ||= K("div", { class: "nx-quick-title" }, [K("h2", null, "代理"), K("p", null, "订阅线路")], -1),
					K("span", { class: k(["nx-quick-state", { "is-live": d.value }]) }, A(d.value ? "已连接" : u.value ? "待连接" : "未配置"), 3)
				]),
				K("div", Vc, [K("strong", null, A(p.value), 1), K("p", null, A(d.value && m.value ? `${m.value} ms · 当前线路` : u.value ? "开启后加载订阅里的节点" : "先去代理页添加订阅"), 1)]),
				K("div", Hc, [K("button", {
					class: k(["btn nx-button", d.value ? "btn--secondary" : "btn--primary"]),
					"aria-pressed": d.value,
					disabled: !!t.session.busy,
					"data-home-proxy": "",
					onClick: b
				}, [q(L(lc), { size: 15 }), J(A(v.value), 1)], 10, Uc), K("button", {
					class: "btn nx-button btn--quiet nx-quick-link",
					"data-home-open": "proxy",
					onClick: r[1] ||= (e) => i("navigate", "proxy")
				}, [r[11] ||= J(" 选线路", -1), q(L(Vs), { size: 13 })])])
			], 2),
			K("section", {
				class: k(["nx-quick-card", { "is-on": h.value > 0 }]),
				"data-home-block": "transfer"
			}, [
				K("header", Wc, [
					K("span", Gc, [q(L(Ys), { size: 19 })]),
					r[12] ||= K("div", { class: "nx-quick-title" }, [K("h2", null, "下载"), K("p", null, "快速取回文件")], -1),
					K("span", { class: k(["nx-quick-state", { "is-live": h.value > 0 }]) }, A(h.value ? "进行中" : "空闲"), 3)
				]),
				K("div", Kc, [K("strong", null, A(h.value ? `${h.value} 个任务` : "没有进行中的下载"), 1), K("p", null, A(h.value ? `${L(bc)(g.value)} 总速度` : "粘贴链接即可开始，默认 8 连接"), 1)]),
				K("div", qc, [K("form", {
					class: "nx-home-download",
					"data-home-download": "",
					onSubmit: bs(x, ["prevent"])
				}, [z(K("input", {
					"onUpdate:modelValue": r[2] ||= (e) => a.value = e,
					class: "nx-input",
					"aria-label": "下载链接",
					placeholder: "粘贴下载链接",
					required: ""
				}, null, 512), [[Q, a.value]]), K("button", {
					class: "btn nx-button btn--primary",
					disabled: !!t.session.busy || !a.value.trim(),
					"aria-label": "开始下载"
				}, [q(L(Ys), { size: 15 })], 8, Jc)], 32), K("button", {
					class: "btn nx-button btn--quiet nx-quick-link",
					"data-home-open": "transfer",
					onClick: r[3] ||= (e) => i("navigate", "transfer")
				}, [r[13] ||= J(" 打开下载页", -1), q(L(Vs), { size: 13 })])])
			], 2)
		])]));
	}
}, Xc = {
	class: "nx-panel nx-speed",
	"data-network-chart": ""
}, Zc = { class: "nx-panel-heading" }, Qc = { class: "nx-speed-values" }, $c = { class: "nx-plot" }, el = {
	key: 0,
	viewBox: "0 0 640 164",
	preserveAspectRatio: "none",
	role: "img",
	"aria-label": "实时下载和上传速度趋势"
}, tl = ["d"], nl = ["d"], rl = ["d"], il = ["d"], al = {
	key: 1,
	class: "nx-chart-wait"
}, ol = { class: "nx-chart-axis" }, sl = { key: 0 }, cl = {
	__name: "SpeedChart",
	props: {
		history: { default: () => [] },
		traffic: { default: null },
		compact: Boolean
	},
	setup(t) {
		let n = t, r = `nx-speed-${vr().replace(/:/g, "")}`, i = Z(() => Math.max(1024, ...n.history.flatMap((e) => [Number(e.download || 0), Number(e.upload || 0)])));
		function a(e) {
			let t = n.history;
			return t.length < 2 ? "" : t.map((n, r) => `${r ? "L" : "M"}${(r / (t.length - 1) * 640).toFixed(2)},${(154 - Number(n[e] || 0) / i.value * 138).toFixed(2)}`).join(" ");
		}
		let o = Z(() => a("download")), s = Z(() => a("upload")), c = Z(() => o.value ? `${o.value} L640,164 L0,164 Z` : "");
		return (n, a) => (U(), W("section", Xc, [
			K("div", Zc, [K("h2", null, [q(L(Ls), { size: 17 }), a[0] ||= J("实时网速", -1)]), a[1] ||= K("span", { class: "nx-subtle" }, "系统接口", -1)]),
			K("div", Qc, [K("span", null, [
				q(L(zs), { size: 17 }),
				K("strong", null, A(L(bc)(t.traffic?.download)), 1),
				a[2] ||= K("small", null, "下载", -1)
			]), K("span", null, [
				q(L(Hs), { size: 17 }),
				K("strong", null, A(L(bc)(t.traffic?.upload)), 1),
				a[3] ||= K("small", null, "上传", -1)
			])]),
			K("div", $c, [t.history.length > 1 ? (U(), W("svg", el, [
				K("defs", null, [K("linearGradient", {
					id: r,
					x1: "0",
					x2: "0",
					y1: "0",
					y2: "1"
				}, [...a[4] ||= [K("stop", {
					offset: "0%",
					"stop-color": "currentColor",
					"stop-opacity": ".18"
				}, null, -1), K("stop", {
					offset: "100%",
					"stop-color": "currentColor",
					"stop-opacity": "0"
				}, null, -1)]])]),
				(U(), W(V, null, B([
					26,
					72,
					118,
					163
				], (e) => K("path", {
					key: e,
					d: `M0,${e}H640`,
					class: "nx-chart-grid"
				}, null, 8, tl)), 64)),
				K("path", {
					d: c.value,
					style: pe({ fill: `url(#${r})` }),
					class: "nx-chart-area"
				}, null, 12, nl),
				K("path", {
					d: s.value,
					class: "nx-chart-upload"
				}, null, 8, rl),
				K("path", {
					d: o.value,
					class: "nx-chart-download"
				}, null, 8, il)
			])) : (U(), W("div", al, [
				q(L(Ls), { size: 22 }),
				a[5] ||= K("span", null, "正在收集网速变化", -1),
				a[6] ||= K("small", null, "新的采样会自动显示在这里", -1)
			]))]),
			K("div", ol, [
				K("span", null, A(t.history.length > 1 ? "较早" : "等待采样"), 1),
				t.history.length > 1 ? (U(), W("span", sl, "最高 " + A(L(e)(i.value)) + "/s", 1)) : Y("", !0),
				a[7] ||= K("span", null, "现在", -1)
			])
		]));
	}
}, ll = { class: "nx-accel-page" }, ul = { class: "nx-accel-orb" }, dl = { class: "nx-accel-copy" }, fl = ["aria-pressed", "disabled"], pl = { class: "nx-accel-grid" }, ml = { class: "nx-panel nx-accel-facts" }, hl = { class: "nx-panel-heading" }, gl = { class: "nx-fact" }, _l = { class: "nx-panel nx-site-check" }, vl = { class: "nx-panel-heading" }, yl = ["disabled"], bl = { class: "nx-site-shortcuts" }, xl = ["onClick"], Sl = {
	key: 0,
	class: "nx-panel nx-recent"
}, Cl = { class: "nx-section-heading" }, wl = {
	__name: "DashboardView",
	props: { session: Object },
	emits: ["navigate", "diagnostic"],
	setup(e, { emit: t }) {
		let n = e, r = t, i = /* @__PURE__ */ I("github.com"), a = Z(() => !!n.session.accelerated);
		async function o() {
			await n.session.toggleAcceleration();
		}
		async function s() {
			let e = await n.session.diagnose(i.value);
			e?.report && r("diagnostic", e.report);
		}
		return (t, n) => (U(), W("div", ll, [
			K("section", { class: k(["nx-accel-control", { "is-on": a.value }]) }, [
				K("div", ul, [q(L(lc), {
					size: 24,
					"stroke-width": 1.7
				})]),
				K("div", dl, [
					n[3] ||= K("span", { class: "nx-kicker" }, "LOCAL ACCELERATION", -1),
					K("h2", null, A(a.value ? "本机加速中" : "未加速"), 1),
					K("p", null, A(a.value ? "本机直连：命中 GitHub、Steam 等常用站点时用 DoH 选 IP。" : "不需要订阅。点一下，用 DoH 选路直连 GitHub、Steam 等常用站点。"), 1)
				]),
				K("button", {
					class: k(["btn nx-button nx-large", a.value ? "btn--secondary" : "btn--primary"]),
					"aria-pressed": a.value,
					disabled: !!e.session.busy || !e.session.systemProxyReady,
					"data-acceleration": "",
					onClick: o
				}, [q(L(lc), { size: 17 }), J(A(e.session.busy === "proxy.start" ? "正在准备线路…" : e.session.busy === "accelerator.start" ? "正在准备…" : e.session.busy === "system.apply" ? "正在开启…" : a.value ? "停止加速" : "一键加速"), 1)], 10, fl)
			], 2),
			K("div", pl, [q(cl, {
				history: e.session.state?.history || [],
				traffic: e.session.state?.traffic
			}, null, 8, ["history", "traffic"]), K("section", ml, [
				K("div", hl, [K("h2", null, [q(L(mc), { size: 17 }), n[4] ||= J("运行方式", -1)])]),
				n[7] ||= K("div", { class: "nx-fact" }, [K("span", null, "加速方式"), K("strong", null, "DoH 选 IP 直连")], -1),
				n[8] ||= K("div", { class: "nx-fact" }, [K("span", null, "系统改动"), K("strong", null, "仅系统代理")], -1),
				n[9] ||= K("div", { class: "nx-fact" }, [K("span", null, "证书 / hosts"), K("strong", null, "不修改")], -1),
				K("div", gl, [n[6] ||= K("span", null, "订阅线路", -1), K("button", {
					class: "btn nx-button btn--quiet nx-fact-link",
					onClick: n[0] ||= (e) => r("navigate", "proxy")
				}, [n[5] ||= J(" 去代理页管理", -1), q(L(Vs), { size: 13 })])]),
				n[10] ||= K("p", { class: "nx-help" }, " 有订阅时会自动准备线路兜底，但不改系统代理；直连失败的域名会记住并优先走线路。 ", -1)
			])]),
			K("div", { class: k(["nx-accel-lower", { "nx-single": !e.session.state?.events?.length }]) }, [K("section", _l, [
				K("div", vl, [K("h2", null, [q(L(rc), { size: 17 }), n[11] ||= J("检查网站访问", -1)])]),
				K("form", {
					class: "nx-inline-form",
					onSubmit: bs(s, ["prevent"])
				}, [z(K("input", {
					"onUpdate:modelValue": n[1] ||= (e) => i.value = e,
					class: "nx-input",
					"aria-label": "要检查的网站",
					placeholder: "输入网址，例如 github.com",
					required: ""
				}, null, 512), [[Q, i.value]]), K("button", {
					class: "btn nx-button btn--secondary",
					disabled: !!e.session.busy
				}, [q(L(Ls), { size: 15 }), J(A(e.session.busy === "diagnose" ? "检查中…" : "检查一下"), 1)], 8, yl)], 32),
				K("div", bl, [n[12] ||= K("span", null, "常用网站", -1), (U(), W(V, null, B([
					"github.com",
					"huggingface.co",
					"google.com"
				], (e) => K("button", {
					key: e,
					class: "btn nx-button btn--quiet",
					onClick: (t) => i.value = e
				}, A(e), 9, xl)), 64))])
			]), e.session.state?.events?.length ? (U(), W("section", Sl, [K("div", Cl, [n[14] ||= K("h2", null, "最近活动", -1), K("button", {
				class: "btn nx-button btn--quiet",
				onClick: n[2] ||= (e) => r("navigate", "advanced")
			}, [n[13] ||= J(" 查看记录", -1), q(L(Vs), { size: 13 })])]), (U(!0), W(V, null, B([...e.session.state.events].reverse().slice(0, 3), (e, t) => (U(), W("div", {
				key: t,
				class: "nx-event"
			}, [
				q(L(Us), { size: 14 }),
				K("span", null, A(e.message), 1),
				K("time", null, A(L(Sc)(e.time)), 1)
			]))), 128))])) : Y("", !0)], 2)
		]));
	}
}, Tl = [
	"checked",
	"disabled",
	"aria-label"
], El = {
	class: "sunday-switch__track",
	"aria-hidden": "true"
}, Dl = { class: "sunday-switch__thumb" }, Ol = {
	key: 0,
	class: "sunday-switch__label"
}, kl = /* @__PURE__ */ _r({
	name: "SundaySwitch",
	__name: "SundaySwitch",
	props: /*@__PURE__*/ ei({
		disabled: {
			type: Boolean,
			default: !1
		},
		label: {},
		size: { default: "md" }
	}, {
		modelValue: {
			type: Boolean,
			default: !1
		},
		modelModifiers: {}
	}),
	emits: ["update:modelValue"],
	setup(e) {
		let t = bi(e, "modelValue");
		function n(e) {
			let n = e.target;
			t.value = n.checked, bn(() => {
				n.checked = t.value;
			});
		}
		return (r, i) => (U(), W("label", { class: k(["sunday-switch", { "sunday-switch--sm": e.size === "sm" }]) }, [
			K("input", {
				class: "sunday-switch__input",
				type: "checkbox",
				role: "switch",
				checked: t.value,
				disabled: e.disabled,
				"aria-label": e.label,
				onChange: n
			}, null, 40, Tl),
			K("span", El, [K("span", Dl, [qr(r.$slots, "thumb")])]),
			r.$slots.default ? (U(), W("span", Ol, [qr(r.$slots, "default")])) : Y("", !0)
		], 2));
	}
}), Al = { class: "nx-panel nx-nodes" }, jl = { class: "nx-panel-heading" }, Ml = { class: "nx-node-head-actions" }, Nl = ["disabled"], Pl = ["disabled"], Fl = {
	class: "nx-line-groups",
	role: "group",
	"aria-label": "线路分组"
}, Il = ["aria-pressed", "onClick"], Ll = { class: "nx-subtle" }, Rl = [
	"data-node",
	"aria-pressed",
	"disabled",
	"onClick"
], zl = { class: "nx-line-radio" }, Bl = { class: "nx-line-name" }, Vl = {
	key: 0,
	class: "nx-subtle nx-line-exit"
}, Hl = { class: "nx-line-ms" }, Ul = [
	"disabled",
	"aria-label",
	"onClick"
], Wl = {
	key: 1,
	class: "nx-empty nx-empty--small"
}, Gl = {
	__name: "NodePicker",
	props: {
		session: Object,
		compact: Boolean
	},
	emits: ["import"],
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(""), r = /* @__PURE__ */ I(""), i = /* @__PURE__ */ I({}), a = Z(() => {
			let e = Object.entries(t.session.proxy?.proxies || {}).filter(([, e]) => Array.isArray(e.all) && e.type === "Selector"), n = t.session.proxy?.mode === "global";
			return e.sort(([e], [t]) => Number(t === "GLOBAL") * (n ? 1 : -1) - Number(e === "GLOBAL") * (n ? 1 : -1));
		});
		Rn(a, (e) => {
			e.some(([e]) => e === n.value) || (n.value = e[0]?.[0] || "");
		}, { immediate: !0 });
		let o = Z(() => a.value.find(([e]) => e === n.value)?.[1]), s = Z(() => (o.value?.all || []).filter((e) => e.toLowerCase().includes(r.value.toLowerCase())));
		function c(e, n = 0) {
			let r = t.session.proxy?.proxies?.[e];
			if (!r) return 0;
			let i = Number(r.history?.at(-1)?.delay);
			if (i > 0) return i;
			let a = r.now;
			return n >= 4 || !a || a === e ? 0 : c(a, n + 1);
		}
		function l(e) {
			let t = i.value[e] ?? c(e);
			return Number(t) > 0 ? Number(t) : 0;
		}
		function u(e) {
			let t = l(e);
			return t > 0 ? `${t} ms` : "未测速";
		}
		function d(e) {
			let n = t.session.proxy?.proxies?.[e];
			if (!n || !Array.isArray(n.all)) return "";
			let r = n.now;
			return r && r !== e ? r : "";
		}
		function f(e) {
			let t = l(e);
			return t ? Math.max(8, Math.round(100 - Math.min(100, t / 3))) : 8;
		}
		function p(e) {
			let t = l(e);
			return t ? t <= 90 ? "is-fast" : t <= 200 ? "is-mid" : "is-slow" : "is-unknown";
		}
		async function m(e) {
			let n = await t.session.run("proxy.delay", { name: e });
			n?.delay != null && (i.value[e] = n.delay);
		}
		async function h() {
			let e = await t.session.optimizeNode(n.value);
			if (e) for (let t of e.candidates || []) Number(t.delay) > 0 && (i.value[t.name] = t.delay);
		}
		return (t, i) => (U(), W("section", Al, [
			K("div", jl, [K("div", null, [i[5] ||= K("span", { class: "nx-kicker" }, "03 / 线路与测速", -1), K("h2", null, [q(L(uc), { size: 17 }), i[4] ||= J("选择线路", -1)])]), K("div", Ml, [K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				"aria-label": "刷新线路",
				disabled: !!e.session.busy,
				onClick: i[0] ||= (t) => e.session.loadProxy()
			}, [q(L(dc), { size: 15 })], 8, Nl), K("button", {
				class: "btn nx-button btn--secondary nx-optimize",
				"data-optimize": "",
				disabled: !!e.session.busy || !s.value.length,
				onClick: h
			}, [q(L(yc), { size: 13 }), J(A(e.session.busy === "proxy.optimize" ? "测速中…" : "选择最快"), 1)], 8, Pl)])]),
			i[9] ||= K("p", { class: "nx-help" }, "点一行直接切换；右侧刷新键单独测速。", -1),
			a.value.length ? (U(), W(V, { key: 0 }, [
				K("div", Fl, [(U(!0), W(V, null, B(a.value, ([e]) => (U(), W("button", {
					key: e,
					class: k(["nx-line-group", { "is-active": n.value === e }]),
					"aria-pressed": n.value === e,
					onClick: (t) => n.value = e
				}, [J(A(e) + " ", 1), K("span", null, A((a.value.length, "")), 1)], 10, Il))), 128)), K("span", Ll, A(s.value.length) + " 条", 1)]),
				s.value.length > 8 ? z((U(), W("input", {
					key: 0,
					"onUpdate:modelValue": i[1] ||= (e) => r.value = e,
					class: "nx-input nx-node-search",
					placeholder: "搜索线路",
					"aria-label": "搜索线路"
				}, null, 512)), [[Q, r.value]]) : Y("", !0),
				K("div", { class: k(["nx-line-list", { "nx-node-list--compact": e.compact }]) }, [(U(!0), W(V, null, B(s.value, (t) => (U(), W("div", {
					key: t,
					class: k(["nx-line-row", { "is-selected": o.value.now === t }])
				}, [K("button", {
					class: "nx-line-choice",
					"data-node": t,
					"aria-pressed": o.value.now === t,
					disabled: !!e.session.busy,
					onClick: (r) => e.session.selectNode(n.value, t)
				}, [
					K("span", zl, [o.value.now === t ? (U(), G(L(Us), {
						key: 0,
						size: 11
					})) : Y("", !0)]),
					K("span", Bl, A(t === "DIRECT" ? "直接连接" : t === "REJECT" ? "阻止连接" : t), 1),
					d(t) ? (U(), W("span", Vl, A(d(t)), 1)) : Y("", !0),
					K("span", { class: k(["nx-line-meter", p(t)]) }, [K("i", { style: pe({ width: `${f(t)}%` }) }, null, 4)], 2),
					K("span", Hl, A(u(t)), 1)
				], 8, Rl), e.compact ? Y("", !0) : (U(), W("button", {
					key: 0,
					class: "btn nx-button btn--quiet nx-icon-button nx-line-refresh",
					disabled: !!e.session.busy,
					"aria-label": `测试 ${t} 的延迟`,
					onClick: (e) => m(t)
				}, [q(L(dc), { size: 13 })], 8, Ul))], 2))), 128))], 2),
				K("button", {
					class: "btn nx-button btn--quiet nx-add-profile",
					onClick: i[2] ||= (e) => t.$emit("import")
				}, [q(L(cc), { size: 14 }), i[6] ||= J("添加或更新订阅 ", -1)])
			], 64)) : (U(), W("div", Wl, [
				q(L(uc), { size: 24 }),
				K("strong", null, A(e.session.state?.proxy?.running ? "尚未找到可选线路" : "开启代理后可切换线路"), 1),
				i[8] ||= K("p", null, "添加订阅，使用你已有的代理节点。", -1),
				K("button", {
					class: "btn nx-button btn--secondary",
					onClick: i[3] ||= (e) => t.$emit("import")
				}, [q(L(cc), { size: 14 }), i[7] ||= J("添加订阅 ", -1)])
			]))
		]));
	}
}, Kl = {
	class: "nx-panel nx-import",
	"data-profile-import": ""
}, ql = { class: "nx-panel-heading" }, Jl = { class: "nx-input-with-action" }, Yl = ["type"], Xl = ["aria-label"], Zl = ["disabled"], Ql = {
	key: 0,
	class: "nx-help"
}, $l = { class: "nx-import-options" }, eu = ["disabled"], tu = ["aria-expanded"], nu = ["disabled"], ru = {
	key: 2,
	class: "nx-help"
}, iu = {
	__name: "ImportProfile",
	props: {
		session: Object,
		autoStart: Boolean
	},
	emits: ["close"],
	setup(e, { emit: t }) {
		let n = e, r = t, i = /* @__PURE__ */ I(""), a = /* @__PURE__ */ I(!1), o = /* @__PURE__ */ I(null), s = /* @__PURE__ */ I(!1), c = /* @__PURE__ */ I("");
		async function l(e) {
			let t = !!n.session.state?.proxy?.running, a = !!n.session.accelerated;
			t && !await n.session.run("proxy.stop", {}, "") || await n.session.run("proxy.config", e, "") && (i.value = "", c.value = "", r("close"), t ? await n.session.run("proxy.start", {}, "") && (n.session.notice = "订阅已更新，线路已重新连接", await n.session.loadProxy(), a && await n.session.toggleAcceleration()) : n.autoStart ? await n.session.toggleAcceleration() : n.session.notice = "订阅已保存，现在可以开启加速");
		}
		async function u(e) {
			let t = e.target.files?.[0];
			if (t) {
				if (t.size > 2 * 1024 * 1024) {
					n.session.error = "配置文件不能超过 2 MB";
					return;
				}
				await l({ content: await t.text() });
			}
		}
		return (t, n) => (U(), W("section", Kl, [
			K("div", ql, [K("h2", null, [q(L(rc), { size: 17 }), n[8] ||= J("添加订阅", -1)]), K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				"aria-label": "收起订阅设置",
				onClick: n[0] ||= (e) => t.$emit("close")
			}, [q(L(vc), { size: 16 })])]),
			n[10] ||= K("p", { class: "nx-help" }, "粘贴你的订阅链接。已有配置文件也可以直接导入。", -1),
			K("form", {
				class: "nx-inline-form",
				onSubmit: n[3] ||= bs((e) => l({ subscription: i.value.trim() }), ["prevent"])
			}, [K("label", Jl, [z(K("input", {
				"onUpdate:modelValue": n[1] ||= (e) => i.value = e,
				type: a.value ? "text" : "password",
				class: "nx-input",
				required: "",
				placeholder: "https://…",
				"aria-label": "订阅链接",
				autocomplete: "off"
			}, null, 8, Yl), [[hs, i.value]]), K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				type: "button",
				"aria-label": a.value ? "隐藏订阅链接" : "显示订阅链接",
				onClick: n[2] ||= (e) => a.value = !a.value
			}, [(U(), G(Wr(a.value ? L(Xs) : L(Zs)), { size: 16 }))], 8, Xl)]), K("button", {
				class: "btn nx-button btn--primary",
				disabled: !!e.session.busy || !i.value.trim()
			}, A(e.session.busy === "proxy.config" ? "正在下载…" : "保存订阅"), 9, Zl)], 32),
			e.session.busy === "proxy.config" ? (U(), W("p", Ql, " 正在下载订阅。慢速订阅可能需要几十秒，请不要关闭页面。 ")) : Y("", !0),
			K("div", $l, [
				K("button", {
					class: "btn nx-button btn--quiet",
					disabled: !!e.session.busy,
					onClick: n[4] ||= (e) => o.value.click()
				}, [q(L($s), { size: 14 }), n[9] ||= J("导入配置文件", -1)], 8, eu),
				K("button", {
					class: "btn nx-button btn--quiet",
					"aria-expanded": s.value,
					onClick: n[5] ||= (e) => s.value = !s.value
				}, A(s.value ? "收起文本配置" : "粘贴配置文本"), 9, tu),
				K("input", {
					ref_key: "fileInput",
					ref: o,
					type: "file",
					accept: ".yaml,.yml,.txt",
					hidden: "",
					onChange: u
				}, null, 544)
			]),
			s.value ? (U(), W("form", {
				key: 1,
				class: "nx-form",
				onSubmit: n[7] ||= bs((e) => l({ content: c.value }), ["prevent"])
			}, [z(K("textarea", {
				"onUpdate:modelValue": n[6] ||= (e) => c.value = e,
				class: "nx-input nx-code",
				rows: "7",
				"aria-label": "代理配置文本",
				placeholder: "粘贴 Mihomo / Clash YAML 配置",
				required: ""
			}, null, 512), [[Q, c.value]]), K("button", {
				class: "btn nx-button btn--secondary",
				disabled: !!e.session.busy
			}, " 保存配置 ", 8, nu)], 32)) : Y("", !0),
			e.session.state?.proxy?.running ? (U(), W("p", ru, " 当前连接已开启。保存订阅或配置时会自动断开并重新连接，不需要手动关闭。 ")) : Y("", !0)
		]));
	}
}, au = { class: "nx-view-stack" }, ou = { class: "nx-section-heading" }, su = { class: "nx-proxy-top" }, cu = { class: "nx-panel nx-subscribe-summary" }, lu = { class: "nx-subscribe-copy" }, uu = { class: "nx-panel nx-proxy-connection" }, du = { class: "nx-proxy-connection-row" }, fu = { class: "nx-route-icon" }, pu = { class: "nx-control-copy" }, mu = {
	__name: "ProxyView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(!1), r = Z(() => !!t.session.state?.proxy?.config_saved);
		return (t, i) => (U(), W("div", au, [
			K("div", ou, [i[5] ||= K("div", null, [
				K("span", { class: "nx-kicker" }, "PROXY DESK"),
				K("h2", null, "订阅与线路"),
				K("p", null, "先有订阅，再选一条线路。")
			], -1), K("button", {
				class: "btn nx-button btn--secondary",
				onClick: i[0] ||= (e) => n.value = !n.value
			}, [q(L(cc), { size: 15 }), J(A(r.value ? "更新订阅" : "添加订阅"), 1)])]),
			n.value ? (U(), G(iu, {
				key: 0,
				session: e.session,
				onClose: i[1] ||= (e) => n.value = !1
			}, null, 8, ["session"])) : Y("", !0),
			K("div", su, [K("section", cu, [
				i[6] ||= K("span", { class: "nx-kicker" }, "01 / 订阅", -1),
				K("div", lu, [K("h3", null, A(r.value ? "订阅已保存" : "还没有订阅"), 1), K("p", null, A(r.value ? "已使用当前 Windows 账户加密保存。更新订阅会自动重连。" : "粘贴服务商给你的 HTTPS 订阅链接，节点会自动出现。"), 1)]),
				K("button", {
					class: k(["btn nx-button", r.value ? "btn--quiet" : "btn--primary"]),
					onClick: i[2] ||= (e) => n.value = !0
				}, [q(L(rc), { size: 14 }), J(A(r.value ? "更新订阅" : "粘贴订阅链接"), 1)], 2)
			]), K("section", uu, [i[7] ||= K("span", { class: "nx-kicker" }, "02 / 连接", -1), K("div", du, [
				K("span", fu, [q(L(lc), { size: 18 })]),
				K("div", pu, [K("strong", null, A(e.session.state?.proxy?.running ? "已连接" : "未连接"), 1), K("p", null, A(r.value ? e.session.state?.proxy?.running ? "节点已加载，可以在下面切换。" : "开启后加载订阅里的节点。" : "先保存订阅，才能启动代理。"), 1)]),
				q(kl, {
					"data-proxy-switch": "",
					label: "代理连接",
					"model-value": !!e.session.state?.proxy?.running,
					disabled: !!e.session.busy || !r.value,
					"onUpdate:modelValue": i[3] ||= (t) => e.session.toggleProxy()
				}, null, 8, ["model-value", "disabled"])
			])])]),
			q(Gl, {
				session: e.session,
				onImport: i[4] ||= (e) => n.value = !0
			}, null, 8, ["session"])
		]));
	}
}, hu = {
	交互内容: "交互内容",
	查看代码: "查看代码",
	"交互内容运行失败，可查看代码或重试": "交互内容运行失败，可查看代码或重试",
	"交互内容过大，请缩小后重试": "交互内容过大，请缩小后重试",
	"交互内容未能加载，可查看代码或重试": "交互内容未能加载，可查看代码或重试",
	成稿: "成稿",
	编辑成稿: "编辑成稿",
	说明: "说明",
	信息: "信息",
	提示: "提示",
	注意: "注意",
	警告: "警告",
	" · 依赖保留": " · 依赖保留",
	" · 待审核 {0}": " · 待审核 {0}",
	" 个": " 个",
	" 个记录": " 个记录",
	" 分组": " 分组",
	" 子代理时间线": " 子代理时间线",
	" 时间线": " 时间线",
	" 条": " 条",
	" 的记录": " 的记录",
	" 输入框": " 输入框",
	"# Sub-agent 委派指南\n在此编写自然语言指令，将注入到主 Agent 系统提示词中…": "# Sub-agent 委派指南\n在此编写自然语言指令，将注入到主 Agent 系统提示词中…",
	"# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…": "# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…",
	"# 输入：{0}": "# 输入：{0}",
	"# 输出：{0}": "# 输出：{0}",
	"# 项目级约束\n项目专属指令，会叠加在全局约束之上…": "# 项目级约束\n项目专属指令，会叠加在全局约束之上…",
	"(项目根)": "(项目根)",
	"* 或工具名，多个用 | 分隔": "* 或工具名，多个用 | 分隔",
	"+ 添加节点": "+ 添加节点",
	"+ 添加输入": "+ 添加输入",
	"+ 添加输出": "+ 添加输出",
	"+ 输入端口": "+ 输入端口",
	"+ 输出端口": "+ 输出端口",
	"AGENTS.md · 移动端全局规则": "AGENTS.md · 移动端全局规则",
	"AGENTS.md 内容": "AGENTS.md 内容",
	"AGENTS.md 已保存": "AGENTS.md 已保存",
	"AI 创意": "AI 创意",
	"AI 模式": "AI 模式",
	"AI（兼容）": "AI（兼容）",
	"API 地址": "API 地址",
	"API 基础 URL": "API 基础 URL",
	"API 基础 URL 必须与所选供应商一致": "API 基础 URL 必须与所选供应商一致",
	"API 配置": "API 配置",
	"Agent 保护区域": "Agent 保护区域",
	"Agent 工具": "Agent 工具",
	"Agent 生成": "Agent 生成",
	"Agent 锁定了这段内容": "Agent 锁定了这段内容",
	"Core App Server 连接失败": "Core App Server 连接失败",
	"DuckDuckGo 本地代理端口": "DuckDuckGo 本地代理端口",
	"DuckDuckGo 本地代理端口（可选）": "DuckDuckGo 本地代理端口（可选）",
	"Enter 续列表 · Tab 缩进": "Enter 续列表 · Tab 缩进",
	"GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。": "GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。",
	"HTTP 代理": "HTTP 代理",
	"ISO 时间": "ISO 时间",
	"JSON 文件与模板": "JSON 文件与模板",
	"Linux 直接运行本机命令，不提供 Windows shell 选择。": "Linux 直接运行本机命令，不提供 Windows shell 选择。",
	"MCP 工具名": "MCP 工具名",
	"MCP 工具名不能为空": "MCP 工具名不能为空",
	"Markdown 笔记工作区": "Markdown 笔记工作区",
	"Python 脚本": "Python 脚本",
	"Python 脚本（兼容）": "Python 脚本（兼容）",
	"Python 表达式": "Python 表达式",
	"RAG 不可用": "RAG 不可用",
	"SKILL.md 正文，加载后应遵循的指引": "SKILL.md 正文，加载后应遵循的指引",
	"Study 未启用": "Study 未启用",
	"Sub Agent 思考模式": "Sub Agent 思考模式",
	"Sub Agent 模型": "Sub Agent 模型",
	"Sunday 工作区": "Sunday 工作区",
	"Sunday 设置": "Sunday 设置",
	"URL 不能为空": "URL 不能为空",
	"Web Search 引擎": "Web Search 引擎",
	"[…截断，仅显示尾部…]\n": "[…截断，仅显示尾部…]\n",
	"^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$": "^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$",
	"^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$": "^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$",
	"at（ISO 时间）": "at（ISO 时间）",
	"baidu（百度，国内可达）": "baidu（百度，国内可达）",
	"bing（必应中文）": "bing（必应中文）",
	"command (Shell 命令)": "command (Shell 命令)",
	"command 不能为空": "command 不能为空",
	"ddg（DuckDuckGo，海外）": "ddg（DuckDuckGo，海外）",
	"hook 失败时阻断执行": "hook 失败时阻断执行",
	"hooks.json 内容": "hooks.json 内容",
	"hooks.json 当前无法解析（不是合法 JSON），已取消保存。请先到「原始配置」视图修复后再添加 Hook。": "hooks.json 当前无法解析（不是合法 JSON），已取消保存。请先到「原始配置」视图修复后再添加 Hook。",
	"http (HTTP 请求)": "http (HTTP 请求)",
	"load_context.jsonc · 移动端全局加载规则": "load_context.jsonc · 移动端全局加载规则",
	"mcp (MCP 工具)": "mcp (MCP 工具)",
	"prompt (内联提示)": "prompt (内联提示)",
	"websearch.jsonc 内容": "websearch.jsonc 内容",
	"y = x * 2（输入端口名当变量，给输出端口名赋值）": "y = x * 2（输入端口名当变量，给输出端口名赋值）",
	"{0} {1}": "{0} {1}",
	"{0} {1} {2}": "{0} {1} {2}",
	"{0} {1} 失败{2}": "{0} {1} 失败{2}",
	"{0} {1} 详情": "{0} {1} 详情",
	"{0} {1}{2}": "{0} {1}{2}",
	"{0} · 文件保留": "{0} · 文件保留",
	"{0} · 项目设置": "{0} · 项目设置",
	"{0} › {1}编辑 {2}": "{0} › {1}编辑 {2}",
	"{0} › 编辑 {1}": "{0} › 编辑 {1}",
	"{0} 个工具": "{0} 个工具",
	"{0} 个文件": "{0} 个文件",
	"{0} 个文件 · {1}": "{0} 个文件 · {1}",
	"{0} 个进程 · {1} 个运行中": "{0} 个进程 · {1} 个运行中",
	"{0} 会话操作": "{0} 会话操作",
	"{0} 分段": "{0} 分段",
	"{0} 分钟前": "{0} 分钟前",
	"{0} 天前": "{0} 天前",
	"{0} 学习进度 {1}%": "{0} 学习进度 {1}%",
	"{0} 小时前": "{0} 小时前",
	"{0} 开关": "{0} 开关",
	"{0} 成果操作": "{0} 成果操作",
	"{0} 文本预览": "{0} 文本预览",
	"{0} 文档": "{0} 文档",
	"{0} 次调用": "{0} 次调用",
	"{0} 段": "{0} 段",
	"{0} 的操作": "{0} 的操作",
	"{0} 的格式工具": "{0} 的格式工具",
	"{0} 的过程": "{0} 的过程",
	"{0} 秒": "{0} 秒",
	"{0} 至 {1}": "{0} 至 {1}",
	"{0} 行": "{0} 行",
	"{0} 详情": "{0} 详情",
	"{0} 附件操作": "{0} 附件操作",
	"{0} 项 · 文件保留": "{0} 项 · 文件保留",
	"{0} 项目操作": "{0} 项目操作",
	"{0}/.lam/config/subagent/settings.json": "{0}/.lam/config/subagent/settings.json",
	"{0}/{1} 在线": "{0}/{1} 在线",
	"{0}s 后重试：{1}": "{0}s 后重试：{1}",
	"{0}{1}": "{0}{1}",
	"{0}关闭 {1}": "{0}关闭 {1}",
	"{0}内容": "{0}内容",
	"{0}分": "{0}分",
	"{0}原上下文已保留": "{0}原上下文已保留",
	"{0}向 {1} 发送消息": "{0}向 {1} 发送消息",
	"{0}天": "{0}天",
	"{0}小时": "{0}小时",
	"{0}必须是正数": "{0}必须是正数",
	"{0}接收 {1} 的消息": "{0}接收 {1} 的消息",
	"{0}操作": "{0}操作",
	"{0}月{1}日": "{0}月{1}日",
	"{0}标题": "{0}标题",
	"{0}说明": "{0}说明",
	"{0}运行详情": "{0}运行详情",
	"{0}颜色节点": "{0}颜色节点",
	"{0}（{1}–{2}）": "{0}（{1}–{2}）",
	"{0}（当前配置）": "{0}（当前配置）",
	"{0}，不可点击": "{0}，不可点击",
	"{0}，打开子代理面板": "{0}，打开子代理面板",
	"· 优先级": "· 优先级",
	"· 历史": "· 历史",
	"· 对话": "· 对话",
	"· 将自动添加模板内模型": "· 将自动添加模板内模型",
	"· 已登录": "· 已登录",
	"· 来源：": "· 来源：",
	"· 运行": "· 运行",
	通过: "通过",
	"。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 上下文」内编辑。": "。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 上下文」内编辑。",
	"「{0}」文件夹里的方案 — 点开读全文，就绪后开工。": "「{0}」文件夹里的方案 — 点开读全文，就绪后开工。",
	"」将被删除": "」将被删除",
	"」将被删除，且无法恢复。": "」将被删除，且无法恢复。",
	"」文件夹里的方案 — 点开读全文，就绪后开工。": "」文件夹里的方案 — 点开读全文，就绪后开工。",
	"」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。": "」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。",
	"」还有没保存的内容，离开就会丢掉。": "」还有没保存的内容，离开就会丢掉。",
	"一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。": "一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。",
	"一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务， 你的数据与配置都留在本机。": "一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务， 你的数据与配置都留在本机。",
	一句话说明这个技能的用途: "一句话说明这个技能的用途",
	一次性: "一次性",
	"一次性触发器需要 at 时间": "一次性触发器需要 at 时间",
	上一步: "上一步",
	上一页附件: "上一页附件",
	上下文: "上下文",
	"上下文 {0}（{1}）": "上下文 {0}（{1}）",
	"上下文、输出、Temperature 与高级适配": "上下文、输出、Temperature 与高级适配",
	上下文占用: "上下文占用",
	上下文压缩: "上下文压缩",
	上下文已压缩: "上下文已压缩",
	上下文窗口: "上下文窗口",
	上下文菜单: "上下文菜单",
	"上传中…": "上传中…",
	上传失败: "上传失败",
	"上传失败 {0} 个 — {1}": "上传失败 {0} 个 — {1}",
	上传文件: "上传文件",
	"上传文件，或让助手把要留存的产出归入资料库。": "上传文件，或让助手把要留存的产出归入库。",
	上移: "上移",
	"上移 {0}": "上移 {0}",
	上级目录: "上级目录",
	上页: "上页",
	下一个模式: "下一个模式",
	下一页附件: "下一页附件",
	下次: "下次",
	下移: "下移",
	"下移 {0}": "下移 {0}",
	"下载 {0}%": "下载 {0}%",
	下载中: "下载中",
	"下载中…": "下载中…",
	下载安装包: "下载安装包",
	"下载完成 100%": "下载完成 100%",
	"下载完成后点击「立即安装」。": "下载完成后点击「立即安装」。",
	"下载完成后请先退出 Sunday，再运行安装包完成升级。": "下载完成后请先退出 Sunday，再运行安装包完成升级。",
	下页: "下页",
	不使用代理的地址: "不使用代理的地址",
	不可用: "不可用",
	不归档: "不归档",
	不迭代: "不迭代",
	不限: "不限",
	"与运行时的确认通道已断开，恢复连接后才能提交选择。": "与运行时的确认通道已断开，恢复连接后才能提交选择。",
	个: "个",
	"个 · 工作流 revision": "个 · 工作流 revision",
	个产物: "个产物",
	个人: "个人",
	个文件: "个文件",
	个条目: "个条目",
	个模型: "个模型",
	"个模型，可来自多个供应商": "个模型，可来自多个供应商",
	个节点: "个节点",
	中: "中",
	"中止（默认）": "中止（默认）",
	中继: "中继",
	"中继.{0}": "中继.{0}",
	中继点: "中继点",
	中间产物: "中间产物",
	"中（默认）": "中（默认）",
	"为 {0} 添加第一个模型": "为 {0} 添加第一个模型",
	"为不同工作模式配置模型可用的工具。": "为不同工作模式配置模型可用的工具。",
	"为供应商添加一个可调用的模型。": "为供应商添加一个可调用的模型。",
	主导航: "主导航",
	主界面: "主界面",
	主题: "主题",
	"主题会即时同步到当前 Sunday 界面。": "主题会即时同步到当前 Sunday 界面。",
	"主题和密度只影响当前 Sunday 界面。": "主题和密度只影响当前 Sunday 界面。",
	主题预设: "主题预设",
	"之后可在 Sunday 设置中继续添加供应商、模型或调整权限模式。": "之后可在 Sunday 设置中继续添加供应商、模型或调整权限模式。",
	事件: "事件",
	"事件 · {0}": "事件 · {0}",
	"事件审计（": "事件审计（",
	事件类型: "事件类型",
	"事件类型，如 artifact.changed": "事件类型，如 artifact.changed",
	"事件触发器需要 event_type": "事件触发器需要 event_type",
	于: "于",
	产品发布: "产品发布",
	产物: "产物",
	人工任务: "人工任务",
	人工任务已提交: "人工任务已提交",
	人工协作: "人工协作",
	人工审批: "人工审批",
	"仅在需要时暴露给 Agent": "仅在需要时暴露给 Agent",
	"仅展示用户、中间产物与产物三类。移除只改变成果库状态，不删除文件。": "仅展示用户、中间产物与产物三类。移除只改变成果库状态，不删除文件。",
	"仅支持 .zip 安装包：{0}": "仅支持 .zip 安装包：{0}",
	仅用于建立设备信任: "仅用于建立设备信任",
	从一个新会话开始: "从一个新会话开始",
	"从左侧文件树打开一篇笔记。": "从左侧文件树打开一篇笔记。",
	"从左侧添加一个模型供应商，开始使用 Sunday。": "从左侧添加一个模型供应商，开始使用 Sunday。",
	从当前环境导入: "从当前环境导入",
	从成果库移除: "从成果库移除",
	"从成果库移除 (": "从成果库移除 (",
	"从成果库移除 {0}": "从成果库移除 {0}",
	"从成果库移除？": "从成果库移除？",
	从收藏移除: "从收藏移除",
	从此处另开会话: "从此处另开会话",
	从此节点运行: "从此节点运行",
	"从此节点运行…": "从此节点运行…",
	"从第 {0} 行": "从第 {0} 行",
	从设备文件中选择: "从设备文件中选择",
	从资料库移除: "从库移除",
	代码: "代码",
	代码开发: "代码开发",
	任务: "任务",
	"任务 {0}…": "任务 {0}…",
	"任务创建后，这里会显示每次运行的时间与结果。": "任务创建后，这里会显示每次运行的时间与结果。",
	任务已处理: "任务已处理",
	任务数量: "任务数量",
	任务标题: "任务标题",
	任务类型: "任务类型",
	"任务类型 {0}": "任务类型 {0}",
	"任务类型“{0}”重复，请保留一条。": "任务类型“{0}”重复，请保留一条。",
	"任务运行中，请先停止任务再分叉": "任务运行中，请先停止任务再分叉",
	"任务运行中，请先停止任务再回退": "任务运行中，请先停止任务再回退",
	"任务运行中，请先停止任务再编辑": "任务运行中，请先停止任务再编辑",
	任务页签: "任务页签",
	份方案: "份方案",
	优先级: "优先级",
	"优先级 {0}": "优先级 {0}",
	会参与激活: "会参与激活",
	会话: "会话",
	会话与项目: "会话与项目",
	会话已重命名: "会话已重命名",
	会话操作: "会话操作",
	会话标题: "会话标题",
	估算: "估算",
	位置: "位置",
	低: "低",
	余烬渐变: "余烬渐变",
	作为引导发送: "作为引导发送",
	"使用官方模板自动填充连接信息和模型。": "使用官方模板自动填充连接信息和模型。",
	"使用选定模型生成结果。": "使用选定模型生成结果。",
	"使用默认应用打开？": "使用默认应用打开？",
	"例如 C:\\certs\\root-ca.pem": "例如 C:\\certs\\root-ca.pem",
	"例如 deepseek-v4-flash": "例如 deepseek-v4-flash",
	"例如 http://127.0.0.1:7890": "例如 http://127.0.0.1:7890",
	"例如 localhost,127.0.0.1,::1,.example.com,*.corp.com": "例如 localhost,127.0.0.1,::1,.example.com,*.corp.com",
	"例如：Free": "例如：Free",
	"例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议": "例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议",
	"例如：invoice.created": "例如：invoice.created",
	"例如：quality >= 0.8": "例如：quality >= 0.8",
	"例如：代码审查": "例如：代码审查",
	"例如：偏好": "例如：偏好",
	"例如：导出显示进度": "例如：导出显示进度",
	"例如：我的供应商": "例如：我的供应商",
	"例如：手机项目": "例如：手机项目",
	"例如：每日同步": "例如：每日同步",
	"例如：用户偏好.md": "例如：用户偏好.md",
	"例如：迭代计划": "例如：迭代计划",
	供应商: "供应商",
	供应商列表: "供应商列表",
	供应商名称: "供应商名称",
	供应商已删除: "供应商已删除",
	供应商已更新: "供应商已更新",
	供应商已添加: "供应商已添加",
	供应商空状态: "供应商空状态",
	供应商详情: "供应商详情",
	供应商配置: "供应商配置",
	依赖: "依赖",
	依赖就绪: "依赖就绪",
	依赖未知: "依赖未知",
	依赖缺失: "依赖缺失",
	侧栏滚动条: "侧栏滚动条",
	拖动调整左侧栏宽度: "拖动调整左侧栏宽度",
	便签: "便签",
	"便签.{0}": "便签.{0}",
	保存: "保存",
	保存中: "保存中",
	"保存中…": "保存中…",
	"保存为所有项目的全局基线；项目可单独覆盖。": "保存为所有项目的全局基线；项目可单独覆盖。",
	保存供应商: "保存供应商",
	"保存冲突，请选择处理方式": "保存冲突，请选择处理方式",
	"保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。": "保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。",
	保存到: "保存到",
	"保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global": "保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global",
	"保存到项目配置 {0}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>": "保存到项目配置 {0}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>",
	"保存到项目配置 {0}/.lam/config/subagent/settings.json。": "保存到项目配置 {0}/.lam/config/subagent/settings.json。",
	"保存后将移除当前项目覆盖，恢复继承全局策略。": "保存后将移除当前项目覆盖，恢复继承全局策略。",
	"保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。": "保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。",
	"保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。",
	"保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。": "保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。",
	"保存失败，修改仍保留在当前编辑器。": "保存失败，修改仍保留在当前编辑器。",
	"保存失败：{0}": "保存失败：{0}",
	"保存失败：{0}。你的草稿仍保留，请核对重合区域。": "保存失败：{0}。你的草稿仍保留，请核对重合区域。",
	"保存失败：笔记已被更新，你的草稿仍保留。": "保存失败：笔记已被更新，你的草稿仍保留。",
	保存工作流: "保存工作流",
	"保存工作流（有未保存修改）": "保存工作流（有未保存修改）",
	保存并切换: "保存并切换",
	保存并继续: "保存并继续",
	保存成员: "保存成员",
	保存模型: "保存模型",
	保存触发器: "保存触发器",
	保存配置: "保存配置",
	保持电脑运行: "保持电脑运行",
	"保留最近的 Step": "保留最近的 Step",
	保留本地修改并用远端版本号重试保存: "保留本地修改并用远端版本号重试保存",
	保留本地并重试: "保留本地并重试",
	信任: "信任",
	修改于: "修改于",
	"修改后需重启后端生效。": "修改后需重启后端生效。",
	"修改范围：原 {0} 行起，新 {1} 行起": "修改范围：原 {0} 行起，新 {1} 行起",
	候选结论: "候选结论",
	值: "值",
	"停止失败：{0}": "停止失败：{0}",
	停止工作流: "停止工作流",
	停止运行: "停止运行",
	"停止运行（子代理仍在运行）": "停止运行（子代理仍在运行）",
	停用: "停用",
	"停用失败：{0}": "停用失败：{0}",
	允许工作目录外: "允许工作目录外",
	允许手机控制这台电脑: "允许手机控制这台电脑",
	允许访问工作目录以外: "允许访问工作目录以外",
	"允许读写工作目录之外的路径。": "允许读写工作目录之外的路径。",
	先保存工作流再排队: "先保存工作流再排队",
	先保存工作流再运行: "先保存工作流再运行",
	先在左侧选择一个项目: "先在左侧选择一个项目",
	"先在左侧选择一个项目 — 资料库跟随项目。": "先在左侧选择一个项目 — 库跟随项目。",
	"先在左侧选择一个项目 — 资料库跟随项目文件夹。": "先在左侧选择一个项目 — 库跟随项目文件夹。",
	"先提供背景方向，其他区域可继续单独调整。": "先提供背景方向，其他区域可继续单独调整。",
	"先用 read_file 读回这份方案（它在当前项目之外，读到它需要你先申请访问批准），对照仓库现状核对需求与步骤，有出入的地方先记下结论；": "先用 read_file 读回这份方案（它在当前项目之外，读到它需要你先申请访问批准），对照仓库现状核对需求与步骤，有出入的地方先记下结论；",
	"先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；": "先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；",
	先进入一个项目: "先进入一个项目",
	"先进入一个项目，再操作它的记忆": "先进入一个项目，再操作它的记忆",
	先选一个工作目录: "先选一个工作目录",
	"克制的中性灰阶。": "克制的中性灰阶。",
	"全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。": "全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。",
	全局上下文加载: "全局上下文加载",
	"全局基线适用于所有项目；项目可按同名任务类型覆盖。": "全局基线适用于所有项目；项目可按同名任务类型覆盖。",
	"全局搜索：跨项目查找会话、消息与学习资料。": "全局搜索：跨项目查找会话、消息与学习资料。",
	全局约束: "全局约束",
	"全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 {0} 条。": "全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 {0} 条。",
	全局记忆: "全局记忆",
	"全应用的出口流量走哪里，以及它们信任哪个根证书。": "全应用的出口流量走哪里，以及它们信任哪个根证书。",
	全选: "全选",
	全部: "全部",
	全部删除: "全部删除",
	全部工具: "全部工具",
	全部工具可用: "全部工具可用",
	全部状态: "全部状态",
	全部类型: "全部类型",
	全部角色: "全部角色",
	公式: "公式",
	"六位数字码 5 分钟内有效且只能使用一次": "六位数字码 5 分钟内有效且只能使用一次",
	"共 {0} 个 · 已信任 {1}{2}": "共 {0} 个 · 已信任 {1}{2}",
	"共 {0} 个 · 已启用 {1}": "共 {0} 个 · 已启用 {1}",
	关于与更新: "关于与更新",
	关系: "关系",
	关系图: "关系图",
	关系图例: "关系图例",
	关系图加载中: "关系图加载中",
	关联: "关联",
	关闭: "关闭",
	关闭并保留草稿: "关闭并保留草稿",
	"恢复默认？": "恢复默认？",
	"将清除已发布的主题与当前草稿，无法撤销。": "将清除已发布的主题与当前草稿，无法撤销。",
	"主题文件过大，请检查是否误选了其他文件": "主题文件过大，请检查是否误选了其他文件",
	"关闭 Sub Agent": "关闭 Sub Agent",
	"关闭 {0} 失败": "关闭 {0} 失败",
	"关闭了 {0}": "关闭了 {0}",
	"关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。": "关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。",
	关闭工作流标签: "关闭工作流标签",
	"关闭提示：{0}": "关闭提示：{0}",
	关闭文本预览: "关闭文本预览",
	关闭网格吸附: "关闭网格吸附",
	关闭节点目录: "关闭节点目录",
	"关闭设置？": "关闭设置？",
	关闭详情: "关闭详情",
	关闭详细调整: "关闭详细调整",
	关闭配对码: "关闭配对码",
	关闭面板: "关闭面板",
	关闭预览: "关闭预览",
	其他: "其他",
	其他处理方式: "其他处理方式",
	"其余时间用另一个模式；跨天时段同样有效。": "其余时间用另一个模式；跨天时段同样有效。",
	兼容: "兼容",
	"兼容旧版 AI 节点。": "兼容旧版 AI 节点。",
	"兼容旧版 Python 脚本节点。": "兼容旧版 Python 脚本节点。",
	"兼容旧版分支节点。": "兼容旧版分支节点。",
	"兼容旧版转换节点。": "兼容旧版转换节点。",
	内存中断自动续跑: "内存中断自动续跑",
	内容宽度: "内容宽度",
	"内容（content）": "内容（content）",
	内核配置: "内核配置",
	内置: "内置",
	内置默认: "内置默认",
	"内置：": "内置：",
	写: "写",
	"写下想法…": "写下想法…",
	"写下注释…": "写下注释…",
	"写点什么，助手下次就会读到它。": "写点什么，助手下次就会读到它。",
	"决定工具执行前是否需要你确认。": "决定工具执行前是否需要你确认。",
	"决定模型是否接收图片，以及是否启用推理参数。": "决定模型是否接收图片，以及是否启用推理参数。",
	"准备开干！": "准备开干！",
	几号: "几号",
	出错: "出错",
	分层: "分层",
	"分支 {0}": "分支 {0}",
	"分支（兼容）": "分支（兼容）",
	分段: "分段",
	分组: "分组",
	"分组.{0}": "分组.{0}",
	分组键: "分组键",
	切换侧栏: "切换侧栏",
	"切换到 ": "切换到 ",
	"切换前要如何处理当前草稿？": "切换前要如何处理当前草稿？",
	切换右侧栏: "切换右侧栏",
	切换模式: "切换模式",
	"切换模式，当前 {0}": "切换模式，当前 {0}",
	"列出 {0}": "列出 {0}",
	列出目录: "列出目录",
	列表视图: "列表视图",
	刚刚: "刚刚",
	刚刚打开: "刚刚打开",
	创建: "创建",
	"创建 {0}": "创建 {0}",
	"创建一个模型组来整理所有供应商下的模型。": "创建一个模型组来整理所有供应商下的模型。",
	创建中: "创建中",
	"创建中…": "创建中…",
	创建了: "创建了",
	创建你的第一个文件夹: "创建你的第一个文件夹",
	创建分组来整理常用模型: "创建分组来整理常用模型",
	"创建失败：{0}": "创建失败：{0}",
	创建定时任务: "创建定时任务",
	创建技能: "创建技能",
	创建文件: "创建文件",
	创建文件夹: "创建文件夹",
	"创建文件夹，整理资料库中的方案。": "创建文件夹，整理库中的方案。",
	创建项目: "创建项目",
	删: "删",
	删除: "删除",
	"删除 ": "删除 ",
	"删除 Hook？": "删除 Hook？",
	"删除 {0}": "删除 {0}",
	"删除 {0} 行": "删除 {0} 行",
	"删除会话及历史？": "删除会话及历史？",
	"删除供应商及其模型配置？": "删除供应商及其模型配置？",
	删除全部队列项和历史: "删除全部队列项和历史",
	删除内容: "删除内容",
	"删除子代理 ": "删除子代理 ",
	删除容器及其内容: "删除容器及其内容",
	删除已结束历史: "删除已结束历史",
	删除待发送内容: "删除待发送内容",
	"删除技能 {0}": "删除技能 {0}",
	"删除技能及目录？": "删除技能及目录？",
	删除文件夹: "删除文件夹",
	"删除文件夹（含里面全部条目）": "删除文件夹（含里面全部条目）",
	删除方案: "删除方案",
	删除标记: "删除标记",
	"删除模型组（模型保留）？": "删除模型组（模型保留）？",
	"删除模型配置？": "删除模型配置？",
	删除此消息及之后内容: "删除此消息及之后内容",
	删除此轮及之后内容: "删除此轮及之后内容",
	删除组: "删除组",
	"删除角色分配 {0}": "删除角色分配 {0}",
	删除记忆: "删除记忆",
	删除连线: "删除连线",
	"删除选中元素（{0}）": "删除选中元素（{0}）",
	删除项目: "删除项目",
	"删除项目及会话记录？": "删除项目及会话记录？",
	刷新: "刷新",
	"刷新中…": "刷新中…",
	刷新人工任务: "刷新人工任务",
	刷新成果库: "刷新成果库",
	刷新激活状态: "刷新激活状态",
	刷新笔记文件树: "刷新笔记文件树",
	刷新进程列表: "刷新进程列表",
	刷新队列: "刷新队列",
	前置: "前置",
	剪切: "剪切",
	加入队列: "加入队列",
	加粗: "加粗",
	"加载 {0} 失败：{1}": "加载 {0} 失败：{1}",
	加载中: "加载中",
	"加载中...": "加载中...",
	"加载中…": "加载中…",
	"加载失败：": "加载失败：",
	"加载失败：{0}": "加载失败：{0}",
	加载技能: "加载技能",
	"加载技能 · {0}": "加载技能 · {0}",
	加载类型: "加载类型",
	助手回复: "助手回复",
	勾选后从成果库移除: "勾选后从成果库移除",
	匹配器: "匹配器",
	"匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。": "匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。",
	单次: "单次",
	"单次 (single)": "单次 (single)",
	"单次 · {0}": "单次 · {0}",
	单步调试: "单步调试",
	"单步运行中…": "单步运行中…",
	卸载: "卸载",
	"卸载插件及目录？": "卸载插件及目录？",
	历史: "历史",
	"压缩保留最近 Step 数": "压缩保留最近 Step 数",
	压缩后: "压缩后",
	压缩未完成: "压缩未完成",
	原上下文已保留: "原上下文已保留",
	"原上下文已保留 · {0}": "原上下文已保留 · {0}",
	原始配置: "原始配置",
	"原文已变化或暂未加载，无法准确定位。": "原文已变化或暂未加载，无法准确定位。",
	"原模型「{0}」已不可用，已改用「{1}」": "原模型「{0}」已不可用，已改用「{1}」",
	去登录: "去登录",
	参数: "参数",
	双击打开: "双击打开",
	双击文本预览: "双击文本预览",
	"发现新版本 v": "发现新版本 v",
	"发现新版本 v{0}": "发现新版本 v{0}",
	"发现新版本 v{0}，点击下载": "发现新版本 v{0}，点击下载",
	"发现新版本 v{0}，点击打开下载页": "发现新版本 v{0}，点击打开下载页",
	发现新版本时会在顶部显示提示条: "发现新版本时会在顶部显示提示条",
	发送: "发送",
	取消: "取消",
	取消下载: "取消下载",
	取消任务: "取消任务",
	取消固定右侧栏: "取消固定右侧栏",
	取消固定左侧栏: "取消固定左侧栏",
	"取消失败：{0}": "取消失败：{0}",
	取消收藏: "取消收藏",
	"取消收藏：{0}": "取消收藏：{0}",
	"取消暴露为 Agent 工具": "取消暴露为 Agent 工具",
	取消更新: "取消更新",
	取消置顶: "取消置顶",
	"取消运行 {0}": "取消运行 {0}",
	"取消选择 {0}": "取消选择 {0}",
	"只属于「{0}」的记忆 — 模型在会话里读它，你在这里整理它。": "只属于「{0}」的记忆 — 模型在会话里读它，你在这里整理它。",
	"只改变背景板，聊天区、输入栏和控件保持中性。": "只改变背景板，聊天区、输入栏和控件保持中性。",
	可用模式: "可用模式",
	可用至: "可用至",
	"可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。": "可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。",
	"可选：自然语言格式说明": "可选：自然语言格式说明",
	右侧工具: "右侧工具",
	右侧工具栏: "右侧工具栏",
	合并: "合并",
	"合并多个输入，取首个有效值。": "合并多个输入，取首个有效值。",
	"同一主题在两种模式下保持不同的明暗气质。": "同一主题在两种模式下保持不同的明暗气质。",
	同步项目: "同步项目",
	名称: "名称",
	名称不能包含路径分隔符: "名称不能包含路径分隔符",
	"后端进程已停止响应（可能已崩溃）。请重启应用以恢复。": "后端进程已停止响应（可能已崩溃）。请重启应用以恢复。",
	"向 Sub Agent 发送消息...": "向 Sub Agent 发送消息...",
	"向 {0} 发送了消息": "向 {0} 发送了消息",
	"向 {0} 发送消息失败": "向 {0} 发送消息失败",
	向下调整高度: "向下调整高度",
	"向供应商 API 发送的模型标识。": "向供应商 API 发送的模型标识。",
	向右调整宽度: "向右调整宽度",
	启动时自动检查更新: "启动时自动检查更新",
	启用: "启用",
	"启用 generate_image 工具": "启用 generate_image 工具",
	启用了: "启用了",
	"启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。": "启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。",
	启用或关闭生图工具: "启用或关闭生图工具",
	"启用技能 {0}": "启用技能 {0}",
	启用推理预算: "启用推理预算",
	"启用插件 {0}": "启用插件 {0}",
	命中: "命中",
	命令: "命令",
	"命令 ": "命令 ",
	"命令 {0}": "命令 {0}",
	"命令…（curl/git/ffmpeg 等）": "命令…（curl/git/ffmpeg 等）",
	命令行: "命令行",
	命令输出: "命令输出",
	回到子代理最新: "回到子代理最新",
	回到最新: "回到最新",
	回到最新消息: "回到最新消息",
	回到编辑: "回到编辑",
	回滚: "回滚",
	"固定 revision": "固定 revision",
	固定右侧栏: "固定右侧栏",
	固定左侧栏: "固定左侧栏",
	图标: "图标",
	图标色彩: "图标色彩",
	图片: "图片",
	"图片加载失败：{0}": "图片加载失败：{0}",
	"图片暂时取不到，重试": "图片暂时取不到，重试",
	图谱: "图谱",
	"在 LamTools 手机端输入此数字": "在 LamTools 手机端输入此数字",
	"在会话里让助手写下记忆，它就会出现在这里。": "在会话里让助手写下记忆，它就会出现在这里。",
	"在当前能力范围内自动批准（工作目录外仍会确认）": "在当前能力范围内自动批准（工作目录外仍会确认）",
	在线: "在线",
	"在聊天里说出你的想法，助手会一边问一边把方案写进「": "在聊天里说出你的想法，助手会一边问一边把方案写进「",
	在里面新建文件夹: "在里面新建文件夹",
	在里面新建记忆: "在里面新建记忆",
	处理中: "处理中",
	"处理中…": "处理中…",
	处理器类型: "处理器类型",
	处理您的日常任务: "处理您的日常任务",
	处理方式: "处理方式",
	备注: "备注",
	复位: "复位",
	复制: "复制",
	复制代码: "复制代码",
	复制回复: "复制回复",
	复制失败: "复制失败",
	"复制失败：当前环境无法访问剪贴板": "复制失败：当前环境无法访问剪贴板",
	"复制完整 ID": "复制完整 ID",
	"复制完整会话 ID": "复制完整会话 ID",
	复制数字码: "复制数字码",
	复制消息: "复制消息",
	复制路径: "复制路径",
	外观: "外观",
	外观模式: "外观模式",
	"外部搜索内核（subprocess / http）": "外部搜索内核（subprocess / http）",
	多模态: "多模态",
	"多模态（支持图片）": "多模态（支持图片）",
	大纲: "大纲",
	失败: "失败",
	"如 AGENTS.md / CONTEXT.md": "如 AGENTS.md / CONTEXT.md",
	"如 gpt-image-1 / flux 等，留空使用服务端默认": "如 gpt-image-1 / flux 等，留空使用服务端默认",
	"如 my-skill（字母/数字/._-）": "如 my-skill（字母/数字/._-）",
	"如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展": "如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展",
	"如：我的 DeepSeek": "如：我的 DeepSeek",
	委派子代理: "委派子代理",
	"委派子代理：{0}": "委派子代理：{0}",
	子代理: "子代理",
	"子代理 (agent)": "子代理 (agent)",
	"子代理 {0}": "子代理 {0}",
	子代理委派策略: "子代理委派策略",
	子代理资源统计: "子代理资源统计",
	子代理运行中: "子代理运行中",
	"子代理运行中：{0}": "子代理运行中：{0}",
	子层: "子层",
	子工作流: "子工作流",
	子文档: "子文档",
	"字段，例如：": "字段，例如：",
	字节读取完成: "字节读取完成",
	学习: "学习",
	"学习、探索、温习": "学习、探索、温习",
	学科: "学科",
	"安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。": "安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。",
	安全边界: "安全边界",
	安装: "安装",
	"安装中…": "安装中…",
	安装依赖: "安装依赖",
	安装包约: "安装包约",
	"安装完成后 Sunday 会自动重新打开。": "安装完成后 Sunday 会自动重新打开。",
	安装成功: "安装成功",
	"安装成功：{0}": "安装成功：{0}",
	安装插件: "安装插件",
	"完全编辑、自动批准，并允许访问工作目录外": "完全编辑、自动批准，并允许访问工作目录外",
	完全访问: "完全访问",
	完全访问已包含: "完全访问已包含",
	"完全访问模式会临时允许访问工作目录之外的路径。": "完全访问模式会临时允许访问工作目录之外的路径。",
	完成: "完成",
	完整归档: "完整归档",
	"完整归档导出失败：{0}": "完整归档导出失败：{0}",
	"完整归档已保存：{0}": "完整归档已保存：{0}",
	"完整归档正在准备中，请稍候。": "完整归档正在准备中，请稍候。",
	"官方发现与 Relay 必须登录": "官方发现与 Relay 必须登录",
	官方模板: "官方模板",
	定时任务: "定时任务",
	"定时任务 › {0}": "定时任务 › {0}",
	"定时任务 › 新建任务": "定时任务 › 新建任务",
	"定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。 点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。": "定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。 点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。",
	定时任务模板: "定时任务模板",
	定时切换: "定时切换",
	实时: "实时",
	实时预览: "实时预览",
	实测: "实测",
	审批: "审批",
	容器内没有可选元素: "容器内没有可选元素",
	宽松: "宽松",
	密码: "密码",
	对话: "对话",
	导入: "导入",
	"导入 JSON": "导入 JSON",
	"导入失败：{0}": "导入失败：{0}",
	导入工作流: "导入工作流",
	导出: "导出",
	"导出失败（{0}）": "导出失败（{0}）",
	"导出失败：{0}": "导出失败：{0}",
	将移除此处的: "将移除此处的",
	"将丢弃：{items}。已完成的工具结果会保留，终止后不能继续。": "将丢弃：{items}。已完成的工具结果会保留，终止后不能继续。",
	"尚未启动 Sub Agent": "尚未启动 Sub Agent",
	"尚未生成配对码。": "尚未生成配对码。",
	尚未登录服务器账号: "尚未登录服务器账号",
	尚未评估: "尚未评估",
	尚未连接: "尚未连接",
	"尚未配对手机。": "尚未配对手机。",
	尝试: "尝试",
	就绪: "就绪",
	局域网: "局域网",
	"局部图超过建议范围（{0} 节点 / {1} 条关系），已保持分页；当前布局在主线程分层计算。": "局部图超过建议范围（{0} 节点 / {1} 条关系），已保持分页；当前布局在主线程分层计算。",
	展开: "展开",
	搜索图层: "搜索图层",
	没有匹配的图层: "没有匹配的图层",
	吸附: "吸附",
	辅助线: "辅助线",
	父级: "父级",
	尺寸: "尺寸",
	宽度: "宽度",
	高度: "高度",
	填充: "填充",
	内容适配: "内容适配",
	固定值: "固定值",
	未设置: "未设置",
	最小: "最小",
	最大: "最大",
	背景透明度: "背景透明度",
	图片格式无法识别: "图片格式无法识别",
	"SVG 不允许包含脚本": "SVG 不允许包含脚本",
	"展开 ": "展开 ",
	"展开 {0}": "展开 {0}",
	"展开{0}分区": "展开{0}分区",
	展开全部会话: "展开全部会话",
	"展开另外 {0} 个会话": "展开另外 {0} 个会话",
	展开最近会话: "展开最近会话",
	展开运行详情: "展开运行详情",
	工作业务: "工作业务",
	工作区: "工作区",
	"工作区域保持纯色，颜色只用于控件层级。": "工作区域保持纯色，颜色只用于控件层级。",
	工作台: "工作台",
	"工作根目录：": "工作根目录：",
	工作模式列表: "工作模式列表",
	工作模式详情: "工作模式详情",
	工作流: "工作流",
	工作流不存在: "工作流不存在",
	工作流名称: "工作流名称",
	工作流对话: "工作流对话",
	工作流有未保存修改: "工作流有未保存修改",
	工作流检查器: "工作流检查器",
	工作流画布: "工作流画布",
	工作流画布操作: "工作流画布操作",
	工作流缩略图: "工作流缩略图",
	工作流节点操作: "工作流节点操作",
	工作流节点目录: "工作流节点目录",
	工作流触发器与激活: "工作流触发器与激活",
	工作流资源: "工作流资源",
	工作流运行输入: "工作流运行输入",
	工作流连线操作: "工作流连线操作",
	工作流队列与历史: "工作流队列与历史",
	工作环境: "工作环境",
	"工作环境：{0}": "工作环境：{0}",
	工作目录: "工作目录",
	"工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。": "工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。",
	工作目录外访问: "工作目录外访问",
	"工作目录外访问设置保存失败，已回滚：{0}": "工作目录外访问设置保存失败，已回滚：{0}",
	工作目录外需确认: "工作目录外需确认",
	工具: "工具",
	"工具 {0} 不可用：请求了当前环境没有注册的工具。": "工具 {0} 不可用：请求了当前环境没有注册的工具。",
	工具不可用: "工具不可用",
	"工具不可用：{0}": "工具不可用：{0}",
	工具列表: "工具列表",
	工具执行前请求批准: "工具执行前请求批准",
	工具模式: "工具模式",
	工具调用: "工具调用",
	工具集: "工具集",
	左对齐: "左对齐",
	已中断: "已中断",
	"已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。": "已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。",
	已保存: "已保存",
	"已保存，重启后端后生效。": "已保存，重启后端后生效。",
	"已保存：{0}": "已保存：{0}",
	"已保留本地修改，正在重试保存…": "已保留本地修改，正在重试保存…",
	已信任: "已信任",
	已修改: "已修改",
	已停用: "已停用",
	"已停用。": "已停用。",
	已停用触发器: "已停用触发器",
	已允许: "已允许",
	已关闭: "已关闭",
	已创建任务: "已创建任务",
	"已创建：{0}": "已创建：{0}",
	"已删除此轮及之后的对话；文件与成果保持不变。": "已删除此轮及之后的对话；文件与成果保持不变。",
	"已加入队列：{0}": "已加入队列：{0}",
	已压缩: "已压缩",
	"已发布 v": "已发布 v",
	已取消: "已取消",
	"已取消完整归档导出。": "已取消完整归档导出。",
	已取消暴露: "已取消暴露",
	已取消队列运行: "已取消队列运行",
	已启用: "已启用",
	已复制: "已复制",
	"已复制 {0} 个元素": "已复制 {0} 个元素",
	"已复制完整会话 ID": "已复制完整会话 ID",
	已失联: "已失联",
	已完成: "已完成",
	"已完成|已失败|已中断|已取消": "已完成|已失败|已中断|已取消",
	"已导入：{0}": "已导入：{0}",
	"已导出工作流 JSON": "已导出工作流 JSON",
	"已导出：{0}": "已导出：{0}",
	已就绪: "已就绪",
	"已就绪 · 已配置密钥": "已就绪 · 已配置密钥",
	已开启: "已开启",
	已截断: "已截断",
	已打开: "已打开",
	已收藏: "已收藏",
	"已新增触发器，请填写配置后保存。": "已新增触发器，请填写配置后保存。",
	"已是最新版本（v": "已是最新版本（v",
	"内部测试版，已跳过应用内更新检查（请用 update-constant.ps1 更新）": "内部测试版，已跳过应用内更新检查（请用 update-constant.ps1 更新）",
	已暂停: "已暂停",
	"已暂停（单步）": "已暂停（单步）",
	已暴露: "已暴露",
	"已暴露：{0}": "已暴露：{0}",
	"已替换并激活。": "已替换并激活。",
	已替换并激活触发器: "已替换并激活触发器",
	已标记: "已标记",
	"已添加 {0} 个目录": "已添加 {0} 个目录",
	"已添加节点：{0}": "已添加节点：{0}",
	"已清理 {0} 个队列/历史项": "已清理 {0} 个队列/历史项",
	"已激活。": "已激活。",
	已激活触发器: "已激活触发器",
	已登录: "已登录",
	已禁用: "已禁用",
	已移除: "已移除",
	"已粘贴 {0} 个元素": "已粘贴 {0} 个元素",
	已获取: "已获取",
	已设为默认模型: "已设为默认模型",
	已评估但未通过: "已评估但未通过",
	"已读取：{0}": "已读取：{0}",
	"已调用{0}个工具…": "已调用{0}个工具…",
	已跳过: "已跳过",
	已运行: "已运行",
	已连接: "已连接",
	已退出: "已退出",
	已选: "已选",
	已选中容器: "已选中容器",
	"已通过，掌握{0}": "已通过，掌握{0}",
	已配对移动设备: "已配对移动设备",
	已配对设备: "已配对设备",
	"已配置（留空保持原密钥）": "已配置（留空保持原密钥）",
	已采用远端版本: "已采用远端版本",
	"已重命名：{0}": "已重命名：{0}",
	已锁定区域: "已锁定区域",
	布局: "布局",
	带输入运行: "带输入运行",
	常量: "常量",
	常量值: "常量值",
	"并发 {0}": "并发 {0}",
	并发上限: "并发上限",
	库根: "库根",
	应用: "应用",
	建议: "建议",
	建议模型: "建议模型",
	"建议模型 {0}": "建议模型 {0}",
	开启: "开启",
	"开启后生成设备身份和一次性六位数字配对码。": "开启后生成设备身份和一次性六位数字配对码。",
	开启手机控制: "开启手机控制",
	开启网格吸附: "开启网格吸附",
	开始: "开始",
	开始使用: "开始使用",
	"开始前需要配置一个模型供应商，让 Agent 能思考与回复。": "开始前需要配置一个模型供应商，让 Agent 能思考与回复。",
	"开始时间（可选）": "开始时间（可选）",
	开始配置: "开始配置",
	开工: "开工",
	引导: "引导",
	引擎: "引擎",
	引用: "引用",
	"引用外部工作流，iterate 控制执行模式": "引用外部工作流，iterate 控制执行模式",
	归到文件夹: "归到文件夹",
	归属此账号的设备: "归属此账号的设备",
	"当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明": "当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明",
	当前主题: "当前主题",
	当前会话: "当前会话",
	当前会话可临时切换: "当前会话可临时切换",
	当前会话说明: "当前会话说明",
	"当前使用内置默认：{0}": "当前使用内置默认：{0}",
	当前供应商: "当前供应商",
	"当前全局基线：{0}": "当前全局基线：{0}",
	当前六位数字配对码: "当前六位数字配对码",
	当前六位配对码: "当前六位配对码",
	"当前内核：{0}": "当前内核：{0}",
	当前显示: "当前显示",
	"当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。": "当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。",
	"当前来源：全局配置": "当前来源：全局配置",
	"当前来源：内置默认（未配置全局 guide）": "当前来源：内置默认（未配置全局 guide）",
	"当前来源：继承全局 / 内置默认（未配置项目级 guide）": "当前来源：继承全局 / 内置默认（未配置项目级 guide）",
	"当前来源：项目配置": "当前来源：项目配置",
	当前桌面工作环境: "当前桌面工作环境",
	当前模型组: "当前模型组",
	当前模式: "当前模式",
	当前模式由插件提供: "当前模式由插件提供",
	"当前步骤：第 {0} 步，{1}，{2}": "当前步骤：第 {0} 步，{1}，{2}",
	"当前没有 checklist": "当前没有 checklist",
	当前没有可分叉的会话: "当前没有可分叉的会话",
	当前没有可回退的会话: "当前没有可回退的会话",
	"当前没有可用的项目，无法打开文件": "当前没有可用的项目，无法打开文件",
	当前没有可编辑的会话: "当前没有可编辑的会话",
	当前没有排队运行: "当前没有排队运行",
	"当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 {0} 条。": "当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 {0} 条。",
	当前版本: "当前版本",
	"当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。": "当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。",
	"当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）": "当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）",
	当前环境不支持文件导出: "当前环境不支持文件导出",
	当前环境不支持文件选择: "当前环境不支持文件选择",
	当前环境不支持附件选择: "当前环境不支持附件选择",
	"当前笔记没有保存处理，修改仍保留。": "当前笔记没有保存处理，修改仍保留。",
	当前组: "当前组",
	"当前继承全局有效策略：{0}": "当前继承全局有效策略：{0}",
	当前计划: "当前计划",
	当前账号: "当前账号",
	"当前选择：{0}": "当前选择：{0}",
	当前配对码: "当前配对码",
	当前队列: "当前队列",
	当前项目: "当前项目",
	"当前项目没有本地覆盖。": "当前项目没有本地覆盖。",
	"当前项目覆盖：{0}": "当前项目覆盖：{0}",
	"当前项目还没有可用会话。新建会话后即可开始工作。": "当前项目还没有可用会话。新建会话后即可开始工作。",
	当前默认状态: "当前默认状态",
	待你选择: "待你选择",
	待处理: "待处理",
	待处理项: "待处理项",
	待定: "待定",
	待审核: "待审核",
	待接入: "待接入",
	待评定: "待评定",
	待配置: "待配置",
	"待配置 · 缺少 API Key": "待配置 · 缺少 API Key",
	循环: "循环",
	"循环 (loop)": "循环 (loop)",
	必填: "必填",
	"必须与所选供应商的 API 基础 URL 一致。": "必须与所选供应商的 API 基础 URL 一致。",
	快捷操作: "快捷操作",
	快速开始: "快速开始",
	思索: "思索",
	思考: "思考",
	"思考中…": "思考中…",
	"思考了{0}s": "思考了{0}s",
	思考了一会: "思考了一会",
	思考模式: "思考模式",
	思考等级: "思考等级",
	思考等级选项: "思考等级选项",
	恢复: "恢复",
	"恢复 {0}": "恢复 {0}",
	恢复到成果库: "恢复到成果库",
	恢复默认: "恢复默认",
	"想了解什么？": "想了解什么？",
	"想如何整理笔记…": "想如何整理笔记…",
	"想学什么…": "想学什么…",
	成员: "成员",
	成果: "成果",
	成果列表: "成果列表",
	成果库: "成果库",
	成果筛选: "成果筛选",
	"我想学{0}，给我讲一下": "我想学{0}，给我讲一下",
	"或粘贴 GitHub Release URL：": "或粘贴 GitHub Release URL：",
	截止: "截止",
	"所选目录在工作区之外，已保留绝对路径": "所选目录在工作区之外，已保留绝对路径",
	手动: "手动",
	手动触发无需排程: "手动触发无需排程",
	手动运行: "手动运行",
	"手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。 自动送达（账号直传）尚未接入，先用导出／导入这一步。": "手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。 自动送达（账号直传）尚未接入，先用导出／导入这一步。",
	手机控制: "手机",
	"手机控制命令将在桌面 Tauri 运行时启用": "手机控制命令将在桌面 Tauri 运行时启用",
	"手机控制命令将在桌面 Tauri 运行时启用。": "手机控制命令将在桌面 Tauri 运行时启用。",
	手机控制未能启动: "手机控制未能启动",
	"手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。": "手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。",
	"手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。": "手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。",
	手机配对: "手机配对",
	打开: "打开",
	"打开 ": "打开 ",
	"打开 {0}": "打开 {0}",
	"打开 {0} 的项目记忆": "打开 {0} 的项目记忆",
	"打开「{0}」失败：{1}": "打开「{0}」失败：{1}",
	"打开会话 {0}": "打开会话 {0}",
	打开右侧面板: "打开右侧面板",
	"打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。": "打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。",
	"打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。": "打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。",
	"打开完整设置（账号与设备）": "打开完整设置（账号与设备）",
	打开工作区: "打开工作区",
	打开左侧会话栏: "打开左侧会话栏",
	"打开快捷操作，当前模式 {0}": "打开快捷操作，当前模式 {0}",
	打开文件夹: "打开文件夹",
	"打开文件夹 {0}": "打开文件夹 {0}",
	打开的工作流: "打开的工作流",
	"打开笔记 {0}": "打开笔记 {0}",
	打开视窗: "打开视窗",
	打开账号与设备: "打开账号与设备",
	打开附件失败: "打开附件失败",
	"打开附件选择器失败：{0}": "打开附件选择器失败：{0}",
	"打开项目 {0}": "打开项目 {0}",
	执行: "执行",
	"执行 Python 脚本，并通过端口传递变量。": "执行 Python 脚本，并通过端口传递变量。",
	执行中: "执行中",
	执行前显示给用户的状态文字: "执行前显示给用户的状态文字",
	"执行动作？": "执行动作？",
	执行步骤: "执行步骤",
	"执行进度：{0}": "执行进度：{0}",
	扩展: "扩展",
	扩展提示: "扩展提示",
	"扩展自身的审批等级与 hard block 由各自的管理入口负责。": "扩展自身的审批等级与 hard block 由各自的管理入口负责。",
	"扫描中…": "扫描中…",
	扫描目录: "扫描目录",
	批准: "批准",
	技能: "技能",
	"技能加载后 Agent 应遵循的完整指引……": "技能加载后 Agent 应遵循的完整指引……",
	把这份方案交给当前会话执行: "把这份方案交给当前会话执行",
	折叠: "折叠",
	"折叠 {0}": "折叠 {0}",
	"折叠{0}分区": "折叠{0}分区",
	折叠最近会话: "折叠最近会话",
	拍摄一张新照片: "拍摄一张新照片",
	拒绝: "拒绝",
	"拖动 {0} 模块排序": "拖动 {0} 模块排序",
	拖动排序: "拖动排序",
	拖动调整宽度: "拖动调整宽度",
	拖动调整宽高: "拖动调整宽高",
	拖动调整高度: "拖动调整高度",
	"拖拽 .zip 文件到此处安装": "拖拽 .zip 文件到此处安装",
	拖拽到这里上传: "拖拽到这里上传",
	指令: "指令",
	"指令…": "指令…",
	指标: "指标",
	按供应商: "按供应商",
	按供应商分类的模型: "按供应商分类的模型",
	"按修改时间（新到旧）": "按修改时间（新到旧）",
	按名称: "按名称",
	"按工作流 input_params 传入": "按工作流 input_params 传入",
	"按条件选择后续分支。": "按条件选择后续分支。",
	按清单使用工具: "按清单使用工具",
	按状态筛选: "按状态筛选",
	按类型筛选: "按类型筛选",
	按组: "按组",
	按组分类的模型: "按组分类的模型",
	"按组新增模型时必须填写 API 基础 URL": "按组新增模型时必须填写 API 基础 URL",
	按角色筛选: "按角色筛选",
	"按计划运行任务，或在需要时随时执行。": "按计划运行任务，或在需要时随时执行。",
	"换个关键词再试。": "换个关键词再试。",
	换个关键词试试: "换个关键词试试",
	排队: "排队",
	消息发送: "消息发送",
	直接引导: "直接引导",
	"Enter 发送方式": "Enter 发送方式",
	"打开时直接按 Enter 会把消息立即交给当前回合；关闭时直接按 Enter 先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种。会话空闲时两个键都开新回合，两个键都不会改动已排队的项。": "打开时直接按 Enter 会把消息立即交给当前回合；关闭时直接按 Enter 先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种。会话空闲时两个键都开新回合，两个键都不会改动已排队的项。",
	"Enter 直接引导": "Enter 直接引导",
	"当前：Enter 直接引导，Ctrl+Enter 排队": "当前：Enter 直接引导，Ctrl+Enter 排队",
	"当前：Enter 排队，Ctrl+Enter 直接引导": "当前：Enter 排队，Ctrl+Enter 直接引导",
	"会话正在运行时发送消息的去向：直接引导会把消息立即交给当前回合；排队会先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种，且两个键都不会改动已排队的项。": "会话正在运行时发送消息的去向：直接引导会把消息立即交给当前回合；排队会先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种，且两个键都不会改动已排队的项。",
	"排队项，可拖拽调整顺序": "排队项，可拖拽调整顺序",
	拖拽调整顺序: "拖拽调整顺序",
	"排队失败：{0}": "排队失败：{0}",
	"排除的默认上下文文件（except）": "排除的默认上下文文件（except）",
	接口类型: "接口类型",
	接口类型与适配参数: "接口类型与适配参数",
	"接收 {0} 消息失败": "接收 {0} 消息失败",
	"接收工作流输入。": "接收工作流输入。",
	控件: "控件",
	控制: "控制",
	"控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。": "控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。",
	"控制新会话的默认权限；当前任务可以在输入框中临时调整。": "控制新会话的默认权限；当前任务可以在输入框中临时调整。",
	"控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。": "控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。",
	"控制过程行前的常规、运行与完成图标；等待和错误仍使用状态色。": "控制过程行前的常规、运行与完成图标；等待和错误仍使用状态色。",
	推理: "推理",
	推理预算: "推理预算",
	"描述（description）": "描述（description）",
	提交: "提交",
	"提交中…": "提交中…",
	"提交数据必须是 JSON 对象": "提交数据必须是 JSON 对象",
	"提交数据必须是有效 JSON": "提交数据必须是有效 JSON",
	"提交数据（JSON）": "提交数据（JSON）",
	提示文本: "提示文本",
	提示文本不能为空: "提示文本不能为空",
	提问: "提问",
	提问自动继续: "提问自动继续",
	插件: "插件",
	"插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件可禁用、不可卸载；每个插件按平台分类（通用 / 桌面端专用 / 移动端专用），本机只列出适用的部分。": "插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件可禁用、不可卸载；每个插件按平台分类（通用 / 桌面端专用 / 移动端专用），本机只列出适用的部分。",
	"插件与 MCP": "插件与 MCP",
	"插件与 MCP 的 hard block 不能从此页解除。": "插件与 MCP 的 hard block 不能从此页解除。",
	更多插件: "更多插件",
	在分屏中打开: "在分屏中打开",
	在右侧分屏中打开: "在右侧分屏中打开",
	在下方分屏中打开: "在下方分屏中打开",
	插件分区: "插件分区",
	插件功能不可用: "插件功能不可用",
	插件未返回有效数据: "插件未返回有效数据",
	"插件目录或 .zip 路径": "插件目录或 .zip 路径",
	"插值）": "插值）",
	"插入 Callout": "插入 Callout",
	"插入 Mermaid 图": "插入 Mermaid 图",
	插入代码块: "插入代码块",
	插入公式: "插入公式",
	插入引用: "插入引用",
	插入表格: "插入表格",
	搜索: "搜索",
	"搜索 {0}": "搜索 {0}",
	"搜索不可用：{0}": "搜索不可用：{0}",
	"搜索中…": "搜索中…",
	"搜索了{0}次": "搜索了{0}次",
	"搜索了{0}次…": "搜索了{0}次…",
	"搜索任务、插件或文件": "搜索任务、插件或文件",
	搜索供应商: "搜索供应商",
	搜索内容: "搜索内容",
	"搜索名称、分类或说明": "搜索名称、分类或说明",
	"搜索名称、路径或来源…": "搜索名称、路径或来源…",
	搜索工作区索引: "搜索工作区索引",
	搜索工具: "搜索工具",
	搜索成果库: "搜索成果库",
	"搜索插件未启用。到「插件」页启用 websearch 后可用。": "搜索插件未启用。到「插件」页启用 websearch 后可用。",
	搜索服务响应正常: "搜索服务响应正常",
	搜索模型: "搜索模型",
	搜索模型组: "搜索模型组",
	搜索模式: "搜索模式",
	搜索结果: "搜索结果",
	搜索节点: "搜索节点",
	搜索范围: "搜索范围",
	搜索记忆: "搜索记忆",
	搜索资料库: "搜索库",
	搜索项目: "搜索项目",
	搜索项目和会话: "搜索项目和会话",
	撤回: "撤回",
	撤销: "撤销",
	撤销后设备立即失去访问权限: "撤销后设备立即失去访问权限",
	"撤销（Ctrl/Cmd+Z）": "撤销（Ctrl/Cmd+Z）",
	操作: "操作",
	操作失败: "操作失败",
	"操作失败：{0}": "操作失败：{0}",
	支持推理: "支持推理",
	"支持注释（JSONC），保存后即时生效。": "支持注释（JSONC），保存后即时生效。",
	"收到了 {0} 的消息": "收到了 {0} 的消息",
	收藏: "收藏",
	"收藏：{0}": "收藏：{0}",
	收起: "收起",
	"收起 ": "收起 ",
	"收起 {0}": "收起 {0}",
	收起会话: "收起会话",
	收起计划: "收起计划",
	收起运行详情: "收起运行详情",
	放大: "放大",
	放大对话: "放大对话",
	放弃: "放弃",
	放弃修改: "放弃修改",
	"放弃未保存的修改？": "放弃未保存的修改？",
	放弃本地修改并采用远端版本: "放弃本地修改并采用远端版本",
	"敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。": "敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。",
	教学示意图: "教学示意图",
	教学配图: "教学配图",
	数据: "数据",
	整理: "整理",
	文件: "文件",
	"文件 {0}": "文件 {0}",
	"文件 · ": "文件 · ",
	文件名: "文件名",
	"文件名（如 TEAM_RULES.md）": "文件名（如 TEAM_RULES.md）",
	文件夹: "文件夹",
	文件夹名: "文件夹名",
	文件夹名称: "文件夹名称",
	文件改动: "文件改动",
	"文件结束 · ": "文件结束 · ",
	文件缺失: "文件缺失",
	文件边界: "文件边界",
	文本: "文本",
	文本操作: "文本操作",
	文本记录: "文本记录",
	文本颜色: "文本颜色",
	"文本（不支持图片）": "文本（不支持图片）",
	文档: "文档",
	文档大纲: "文档大纲",
	文档知识: "文档知识",
	斜体: "斜体",
	新任务: "新任务",
	新会话将从这里开始: "新会话将从这里开始",
	新会话默认: "新会话默认",
	"新供应商需要填写名称和 API Key": "新供应商需要填写名称和 API Key",
	新增: "新增",
	"新增 Hook": "新增 Hook",
	"新增 {0} 行": "新增 {0} 行",
	"新增一个模式后，就可以设置它能使用的工具。": "新增一个模式后，就可以设置它能使用的工具。",
	新增供应商: "新增供应商",
	新增模型: "新增模型",
	新增模式: "新增模式",
	新增第一条角色分配: "新增第一条角色分配",
	新增触发器: "新增触发器",
	新建: "新建",
	新建任务: "新建任务",
	新建会话: "新建会话",
	新建定时任务: "新建定时任务",
	新建工作流: "新建工作流",
	新建技能: "新建技能",
	新建文件夹: "新建文件夹",
	"新建文件夹…": "新建文件夹…",
	新建方案: "新建方案",
	新建模型组: "新建模型组",
	新建节点: "新建节点",
	新建记忆: "新建记忆",
	新建项目: "新建项目",
	方案: "方案",
	方案传输: "方案传输",
	方案名称: "方案名称",
	"方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态": "方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态",
	方案编辑: "方案编辑",
	方案阅读: "方案阅读",
	无依赖: "无依赖",
	无多模态模型: "无多模态模型",
	无工具: "无工具",
	无序列表: "无序列表",
	无技能: "无技能",
	"无法创建模型组 {0}": "无法创建模型组 {0}",
	"无法打开学习会话，请重试": "无法打开学习会话，请重试",
	"无法打开：{0}": "无法打开：{0}",
	无法显示: "无法显示",
	"无法更新连线：端口类型不兼容或端口不存在": "无法更新连线：端口类型不兼容或端口不存在",
	"无法读取文本：{0}": "无法读取文本：{0}",
	"无法连接服务器：{0}": "无法连接服务器：{0}",
	"无法连接：端口类型不兼容或端口不存在": "无法连接：端口类型不兼容或端口不存在",
	无钩子: "无钩子",
	无需压缩: "无需压缩",
	日: "日",
	日出渐变: "日出渐变",
	日历: "日历",
	日历触发器需要时间: "日历触发器需要时间",
	日历频率: "日历频率",
	日志: "日志",
	日期: "日期",
	时区: "时区",
	时间: "时间",
	"时间 {0}": "时间 {0}",
	映射: "映射",
	"显式替换现有激活，并固定到当前 revision": "显式替换现有激活，并固定到当前 revision",
	显示名称: "显示名称",
	显示已移除: "显示已移除",
	显示更早的过程: "显示更早的过程",
	显示模块: "显示模块",
	晨会摘要: "晨会摘要",
	晨宵: "晨宵",
	智能: "智能",
	智能体: "智能体",
	"智能体目标…": "智能体目标…",
	"暂不可用：{0}": "暂不可用：{0}",
	暂停: "暂停",
	"暂停工作流，等待人工批准或拒绝。": "暂停工作流，等待人工批准或拒绝。",
	暂无: "暂无",
	暂无上下文: "暂无上下文",
	暂无上下文统计: "暂无上下文统计",
	暂无会话: "暂无会话",
	"暂无内容，创建一个开始。": "暂无内容，创建一个开始。",
	"暂无可显示的 Sub Agent 事件。": "暂无可显示的 Sub Agent 事件。",
	暂无可添加的模型: "暂无可添加的模型",
	暂无可用工具: "暂无可用工具",
	暂无可用数据: "暂无可用数据",
	暂无可用模型: "暂无可用模型",
	"暂无可用模型，可手动输入模型 ID": "暂无可用模型，可手动输入模型 ID",
	暂无已登记项目: "暂无已登记项目",
	"暂无已登记项目。": "暂无已登记项目。",
	"暂无已移除的成果。": "暂无已移除的成果。",
	暂无待处理任务: "暂无待处理任务",
	"暂无消息，发送一个任务。": "暂无消息，发送一个任务。",
	"暂无笔记关系。": "暂无笔记关系。",
	"暂无符合筛选条件的成果。": "暂无符合筛选条件的成果。",
	暂无节点: "暂无节点",
	"暂无触发器。新增后可配置手动或定时入口。": "暂无触发器。新增后可配置手动或定时入口。",
	"暂无资源统计。": "暂无资源统计。",
	"暴露为 Agent 工具": "暴露为 Agent 工具",
	更多: "更多",
	更新: "更新",
	"更新 v{0} 已下载并校验，点击安装": "更新 v{0} 已下载并校验，点击安装",
	更新于: "更新于",
	更新任务清单: "更新任务清单",
	更新定时任务失败: "更新定时任务失败",
	"更新模型标识、能力和运行参数。": "更新模型标识、能力和运行参数。",
	更新计划: "更新计划",
	"更新连接信息，已有密钥不会被覆盖。": "更新连接信息，已有密钥不会被覆盖。",
	替换并激活: "替换并激活",
	最低思考强度: "最低思考强度",
	"最低思考强度 {0}": "最低思考强度 {0}",
	最后一个: "最后一个",
	最多运行次数: "最多运行次数",
	最大化: "最大化",
	最大并发: "最大并发",
	最大输出: "最大输出",
	最大运行次数: "最大运行次数",
	"最大运行次数（可选）": "最大运行次数（可选）",
	最大迭代: "最大迭代",
	最小化: "最小化",
	"最小间隔（秒）": "最小间隔（秒）",
	最新版本: "最新版本",
	最近: "最近",
	"最近一次 {0}": "最近一次 {0}",
	最近任务: "最近任务",
	最近打开: "最近打开",
	最近项目: "最近项目",
	最高思考强度: "最高思考强度",
	"最高思考强度 {0}": "最高思考强度 {0}",
	有序列表: "有序列表",
	有效期至: "有效期至",
	有新版本可用: "有新版本可用",
	有未保存修改: "有未保存修改",
	有未保存的修改: "有未保存的修改",
	服务器: "服务器",
	"服务器地址必须使用 HTTP 或 HTTPS": "服务器地址必须使用 HTTP 或 HTTPS",
	服务器地址格式无效: "服务器地址格式无效",
	"服务器未返回有效的桌面 Node": "服务器未返回有效的桌面 Node",
	"服务器请求失败（{0}）": "服务器请求失败（{0}）",
	服务器账号: "服务器账号",
	服务器返回了无效的登录凭据: "服务器返回了无效的登录凭据",
	服务地址: "服务地址",
	未上报: "未上报",
	未上报缓存: "未上报缓存",
	未保存: "未保存",
	未关联供应商: "未关联供应商",
	未分组: "未分组",
	"未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。": "未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。",
	"未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为": "未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为",
	未发现新目录: "未发现新目录",
	未启用: "未启用",
	未命中: "未命中",
	未命名定时任务: "未命名定时任务",
	未命名工作流: "未命名工作流",
	未命名来源: "未命名来源",
	未命名节点: "未命名节点",
	未命名运行: "未命名运行",
	未命名项目: "未命名项目",
	"未安装 RAG 插件；可尝试兼容搜索": "未安装 RAG 插件；可尝试兼容搜索",
	未找到匹配的项目或会话: "未找到匹配的项目或会话",
	"未找到对应笔记，无法导航。": "未找到对应笔记，无法导航。",
	"未找到该消息（可能已被删除或属于子会话）": "未找到该消息（可能已被删除或属于子会话）",
	"未找到：{0}": "未找到：{0}",
	未指定: "未指定",
	未提供命令: "未提供命令",
	"未提取到正文摘要。": "未提取到正文摘要。",
	未检查: "未检查",
	未激活: "未激活",
	未登录: "未登录",
	未知: "未知",
	未知命令: "未知命令",
	未知触发方式: "未知触发方式",
	未获取: "未获取",
	"未获得收益 · ": "未获得收益 · ",
	"未记录任务内容。": "未记录任务内容。",
	未设置事件: "未设置事件",
	未设置时间: "未设置时间",
	"未设置（可在设置中调整）": "未设置（可在设置中调整）",
	未运行: "未运行",
	未连接到搜索服务: "未连接到搜索服务",
	未选择: "未选择",
	未配置: "未配置",
	"未配置（使用内置兜底：{0}）": "未配置（使用内置兜底：{0}）",
	"未回答的子代理提问 {count} 个": "未回答的子代理提问 {count} 个",
	未完成的步骤: "未完成的步骤",
	"本地 zip 路径": "本地 zip 路径",
	本地目录: "本地目录",
	本机: "本机",
	"本机命令工具使用的 shell": "本机命令工具使用的 shell",
	本机身份: "本机身份",
	本轮产出: "本轮产出",
	"机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。": "机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。",
	权限: "权限",
	"权限偏好保存失败：{0}": "权限偏好保存失败：{0}",
	权限审批: "权限审批",
	"权限审批与输入框保持一致；工具清单由“工具模式”管理。": "权限审批与输入框保持一致；工具清单由“工具模式”管理。",
	权限审批选项: "权限审批选项",
	"权限模式保存失败，已回滚：{0}": "权限模式保存失败，已回滚：{0}",
	条件: "条件",
	条关系: "条关系",
	条用户指令: "条用户指令",
	来源: "来源",
	来自子代理: "来自子代理",
	松开以安装: "松开以安装",
	松开鼠标上传附件: "松开鼠标上传附件",
	极光渐变: "极光渐变",
	极高: "极高",
	构建稳定的工作流程: "构建稳定的工作流程",
	查看: "查看",
	"查看 git 差异": "查看 git 差异",
	"查看 git 状态": "查看 git 状态",
	查看全文: "查看全文",
	"查看其余 ": "查看其余 ",
	"查看其余 {0} 步": "查看其余 {0} 步",
	查看发布说明: "查看发布说明",
	查看官方文档: "查看官方文档",
	标准: "标准",
	标准输出: "标准输出",
	标记: "标记",
	标题: "标题",
	"标题（name）": "标题（name）",
	框架: "框架",
	"框架.{0}": "框架.{0}",
	桌面端专用: "桌面端专用",
	"档位 全局档": "档位 全局档",
	"档位 项目档": "档位 项目档",
	"检查中…": "检查中…",
	"检查失败：": "检查失败：",
	检查更新: "检查更新",
	"检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。": "检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。",
	检查连接: "检查连接",
	"检测到版本冲突，但无法读取远端版本：{0}": "检测到版本冲突，但无法读取远端版本：{0}",
	"检测到版本冲突，远端版本暂不可读取": "检测到版本冲突，远端版本暂不可读取",
	森林渐变: "森林渐变",
	棱镜渐变: "棱镜渐变",
	模型: "模型",
	"模型 ID": "模型 ID",
	"模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。": "模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。",
	模型与供应商: "模型",
	"模型与供应商、外观主题、工具权限等应用配置。": "模型、外观主题、工具权限等应用配置。",
	模型与思考参数: "模型与思考参数",
	"模型与思考强度：{0} {1}": "模型与思考强度：{0} {1}",
	模型分类方式: "模型分类方式",
	"模型分类方式保存失败，已回滚：{0}": "模型分类方式保存失败，已回滚：{0}",
	"模型列表加载失败，可手动输入": "模型列表加载失败，可手动输入",
	"模型可同时存在于多个组；删除组不会删除模型。": "模型可同时存在于多个组；删除组不会删除模型。",
	模型已创建并加入分组: "模型已创建并加入分组",
	模型已删除: "模型已删除",
	模型已更新: "模型已更新",
	模型已添加: "模型已添加",
	"模型指令…": "模型指令…",
	模型数量: "模型数量",
	模型组: "模型组",
	模型组列表: "模型组列表",
	模型组已创建: "模型组已创建",
	模型组已删除: "模型组已删除",
	模型组已更新: "模型组已更新",
	模型组成员: "模型组成员",
	模型组成员已更新: "模型组成员已更新",
	模型组空状态: "模型组空状态",
	模型组详情: "模型组详情",
	模型能力: "模型能力",
	模型选项: "模型选项",
	模型配置: "模型配置",
	模式: "模式",
	模式名: "模式名",
	"模式名不能为空，已取消保存": "模式名不能为空，已取消保存",
	"模式名重复：{0}，已取消保存": "模式名重复：{0}，已取消保存",
	模式说明: "模式说明",
	模板: "模板",
	模板入口: "模板入口",
	横向分布: "横向分布",
	横向滚动表格: "横向滚动表格",
	橙色: "橙色",
	次: "次",
	次数: "次数",
	"次调用 ·": "次调用 ·",
	"欢迎使用 Sunday": "欢迎使用 Sunday",
	正在: "正在",
	"正在下载 v{0}…": "正在下载 v{0}…",
	"正在下载…": "正在下载…",
	正在下载更新: "正在下载更新",
	"正在保存…": "正在保存…",
	"正在保存项目更改…": "正在保存项目更改…",
	"正在停止…": "正在停止…",
	"正在准备完整归档，请稍候…": "正在准备完整归档，请稍候…",
	"正在创建…": "正在创建…",
	正在刷新进程列表: "正在刷新进程列表",
	"正在加载…": "正在加载…",
	正在加载历史消息: "正在加载历史消息",
	"正在加载工具模式…": "正在加载工具模式…",
	"正在加载成果库…": "正在加载成果库…",
	正在加载更早消息: "正在加载更早消息",
	"正在加载笔记…": "正在加载笔记…",
	正在压缩上下文: "正在压缩上下文",
	正在同步: "正在同步",
	"正在回答…": "正在回答…",
	正在处理: "正在处理",
	"正在安装…": "正在安装…",
	正在安装更新: "正在安装更新",
	"正在打开…": "正在打开…",
	"正在检查…": "正在检查…",
	"正在生成配对码…": "正在生成配对码…",
	"正在读取 Sub Agent 记录...": "正在读取 Sub Agent 记录...",
	"正在读取…": "正在读取…",
	"正在读取后台进程…": "正在读取后台进程…",
	"正在读取定时任务…": "正在读取定时任务…",
	"正在读取文本…": "正在读取文本…",
	"正在读取记忆…": "正在读取记忆…",
	"正在读取资料库…": "正在读取库…",
	"正在读取项目…": "正在读取项目…",
	正在输出: "正在输出",
	正常: "正常",
	正文: "正文",
	"正在运行或已暂停的子代理 {count} 个": "正在运行或已暂停的子代理 {count} 个",
	此容器: "此容器",
	"此操作不可撤销，将": "此操作不可撤销，将",
	"此文件将交给系统默认应用处理。": "此文件将交给系统默认应用处理。",
	此模块暂不可用: "此模块暂不可用",
	此模块未启用: "此模块未启用",
	此电脑: "此电脑",
	此节点: "此节点",
	此节点暂不支持可视化配置: "此节点暂不支持可视化配置",
	步: "步",
	步骤: "步骤",
	"步：": "步：",
	每: "每",
	"每 {0} 秒": "每 {0} 秒",
	每天: "每天",
	"每天 {0}": "每天 {0}",
	每月: "每月",
	"每月 {0} 日 {1}": "每月 {0} 日 {1}",
	"每月日期必须是 1 到 31": "每月日期必须是 1 到 31",
	每月第几天: "每月第几天",
	每次新建: "每次新建",
	每行一个: "每行一个",
	"每隔（秒）": "每隔（秒）",
	水平居中: "水平居中",
	"汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。": "汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。",
	汇聚: "汇聚",
	"汇聚具名输入并收集为对象。": "汇聚具名输入并收集为对象。",
	"没有匹配「{0}」的结果 — 换个关键词，或切到「全部」看看其他范围": "没有匹配「{0}」的结果 — 换个关键词，或切到「全部」看看其他范围",
	没有匹配的供应商: "没有匹配的供应商",
	没有匹配的模型: "没有匹配的模型",
	没有匹配的模型组: "没有匹配的模型组",
	没有匹配的模式: "没有匹配的模式",
	没有匹配的节点: "没有匹配的节点",
	没有匹配的项目: "没有匹配的项目",
	没有匹配结果: "没有匹配结果",
	没有可切换的插件模式: "没有可切换的插件模式",
	没有找到匹配的工具: "没有找到匹配的工具",
	没有正在登记的后台进程: "没有正在登记的后台进程",
	没有长期后台进程: "没有长期后台进程",
	"注入优先级（越小越靠前）": "注入优先级（越小越靠前）",
	注入到上下文的提示文本: "注入到上下文的提示文本",
	注册: "注册",
	注释: "注释",
	"注释.{0}": "注释.{0}",
	浅色: "浅色",
	浅色从: "浅色从",
	"浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。": "浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。",
	"浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。": "浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。",
	浅色开始时间: "浅色开始时间",
	测试: "测试",
	测试失败: "测试失败",
	测试超时: "测试超时",
	测试通过: "测试通过",
	浏览: "浏览",
	"浏览…": "浏览…",
	"浏览了{0}个目录": "浏览了{0}个目录",
	"浏览了{0}个目录…": "浏览了{0}个目录…",
	浮梦: "浮梦",
	海洋渐变: "海洋渐变",
	消息附件: "消息附件",
	淡灰: "淡灰",
	深色: "深色",
	深色从: "深色从",
	深色开始时间: "深色开始时间",
	添加: "添加",
	"添加一个 OpenAI Compatible 或其他模型供应商": "添加一个 OpenAI Compatible 或其他模型供应商",
	添加一条简短说明: "添加一条简短说明",
	添加供应商: "添加供应商",
	添加到: "添加到",
	添加到当前会话: "添加到当前会话",
	添加到收藏: "添加到收藏",
	添加到文件夹: "添加到文件夹",
	添加已有模型: "添加已有模型",
	添加模型: "添加模型",
	"添加现有模型，或创建一个新模型": "添加现有模型，或创建一个新模型",
	"添加节点…": "添加节点…",
	"添加节点：{0}": "添加节点：{0}",
	添加计划: "添加计划",
	添加附件: "添加附件",
	清单: "清单",
	清理历史: "清理历史",
	"清理失败：{0}": "清理失败：{0}",
	清空全部: "清空全部",
	清除: "清除",
	"清除“全部工具”后，可以单独选择需要开放的工具。": "清除“全部工具”后，可以单独选择需要开放的工具。",
	清除搜索: "清除搜索",
	清除节点目录搜索: "清除节点目录搜索",
	渐变角度: "渐变角度",
	温度: "温度",
	激活: "激活",
	"激活会固定当前工作流 revision": "激活会固定当前工作流 revision",
	"激活失败：{0}": "激活失败：{0}",
	"激活状态刷新失败：{0}": "激活状态刷新失败：{0}",
	"灰线：未上报缓存": "灰线：未上报缓存",
	灰色区压缩: "灰色区压缩",
	灵感构思: "灵感构思",
	"点击“生成配对码”开始配对。": "点击“生成配对码”开始配对。",
	"点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。": "点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。",
	"点此申请 API key": "点此申请 API key",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。": "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工；方案文件的更新写回它原来的位置。": "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工；方案文件的更新写回它原来的位置。",
	版本不符: "版本不符",
	版本信息: "版本信息",
	"版本；切换后立即生效。": "版本；切换后立即生效。",
	状态: "状态",
	"状态消息 (可选)": "状态消息 (可选)",
	"状态：{0}": "状态：{0}",
	生图: "生图",
	"生成 {0}": "生成 {0}",
	生成中: "生成中",
	生成图片: "生成图片",
	生成工具输入: "生成工具输入",
	生成配对码: "生成配对码",
	"用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。": "用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。",
	用一句话说明要怎么处理: "用一句话说明要怎么处理",
	"用于侧边栏中的项目辨识。": "用于侧边栏中的项目辨识。",
	用户: "用户",
	用户上传: "用户上传",
	用户名: "用户名",
	用户指令导航: "用户指令导航",
	用户消息: "用户消息",
	电脑: "电脑",
	画布元素: "画布元素",
	画布元素操作: "画布元素操作",
	画布布局工具: "画布布局工具",
	界面: "界面",
	界面密度: "界面密度",
	界面语言: "界面语言",
	留空不限: "留空不限",
	留空以保留现有密钥: "留空以保留现有密钥",
	留空时使用目录名称: "留空时使用目录名称",
	"留空时直连；填写后使用 http://127.0.0.1:端口。": "留空时直连；填写后使用 http://127.0.0.1:端口。",
	登录: "登录",
	"登录 / 账号": "登录 / 账号",
	"登录后在手机上配对，这里会列出已配对的设备。": "登录后在手机上配对，这里会列出已配对的设备。",
	"登录状态与已配对的设备。": "登录状态与已配对的设备。",
	的: "的",
	"的模型。": "的模型。",
	"目录 ": "目录 ",
	"目录名 + frontmatter name": "目录名 + frontmatter name",
	"目录路径（工作区相对或绝对）": "目录路径（工作区相对或绝对）",
	目标: "目标",
	目标与待发送输入: "目标与待发送输入",
	相关设置: "相关设置",
	相册: "相册",
	相机: "相机",
	知识关系: "知识关系",
	知识图谱: "知识图谱",
	知识层级: "知识层级",
	知道了: "知道了",
	"确定删除“{0}”及其内部 {1} 个元素？此操作不可撤销。": "确定删除“{0}”及其内部 {1} 个元素？此操作不可撤销。",
	确认: "确认",
	确认删除: "确认删除",
	确认放弃修改: "确认放弃修改",
	确认清理: "确认清理",
	确认清理队列: "确认清理队列",
	确认移除: "确认移除",
	"确认（{0}秒）": "确认（{0}秒）",
	禁止: "禁止",
	"禁用技能 {0}": "禁用技能 {0}",
	"禁用插件 {0}": "禁用插件 {0}",
	离线: "离线",
	秒: "秒",
	移出组: "移出组",
	移动: "移动",
	移动端专用: "移动端专用",
	移动端快捷操作: "移动端快捷操作",
	移动设备: "移动设备",
	移除: "移除",
	"移除 {0}": "移除 {0}",
	移除计划: "移除计划",
	移除记录: "移除记录",
	"移除进程 ": "移除进程 ",
	"空值表示无条件；表达式不满足时，下游会跳过。": "空值表示无条件；表达式不满足时，下游会跳过。",
	空闲: "空闲",
	"窗口（秒）": "窗口（秒）",
	立即安装: "立即安装",
	端口: "端口",
	笔记: "笔记",
	笔记关系图: "笔记关系图",
	笔记关联: "笔记关联",
	笔记助手: "笔记助手",
	笔记库: "笔记库",
	笔记总体关系图: "笔记总体关系图",
	笔记文件树: "笔记文件树",
	笔记来源: "笔记来源",
	笔记节点: "笔记节点",
	第: "第",
	"第 {0} / {1} 项": "第 {0} / {1} 项",
	"第 {0} 条用户指令，共 {1} 条": "第 {0} 条用户指令，共 {1} 条",
	"第 {0} 条角色分配必须选择建议模型。": "第 {0} 条角色分配必须选择建议模型。",
	"第 {0} 条角色分配的任务类型不能为空。": "第 {0} 条角色分配的任务类型不能为空。",
	"第 {0} 条角色分配的最低思考强度不能高于最高思考强度。": "第 {0} 条角色分配的最低思考强度不能高于最高思考强度。",
	"第 {0} 行": "第 {0} 行",
	"第 {0}/{1} 段": "第 {0}/{1} 段",
	等待: "等待",
	等待中: "等待中",
	等待事件: "等待事件",
	等待你的选择: "等待你的选择",
	"等待外部事件后继续执行。": "等待外部事件后继续执行。",
	等待选择: "等待选择",
	等待回答: "等待回答",
	策略: "策略",
	"策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。": "策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。",
	筛选资料: "筛选资料",
	筛选资料库: "筛选库",
	"管理 web_search 工具使用的搜索引擎内核与网络代理，保存到 websearch 插件配置后即时生效。": "管理 web_search 工具使用的搜索引擎内核与网络代理，保存到 websearch 插件配置后即时生效。",
	"管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。": "管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。",
	管理你的知识: "管理你的知识",
	管理定时任务: "管理定时任务",
	"管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。": "管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。",
	"管理已安装的插件，开关它们带来的界面与工具。": "管理已安装的插件，开关它们带来的界面与工具。",
	"管理模型接入、供应商配置与默认模型选择。": "管理模型接入、供应商配置与默认模型选择。",
	管理目标: "管理目标",
	类型: "类型",
	"类型 {0}": "类型 {0}",
	粉色: "粉色",
	粘贴: "粘贴",
	"粘贴失败：当前环境无法读取剪贴板": "粘贴失败：当前环境无法读取剪贴板",
	系统: "系统",
	系统打开: "系统打开",
	"系统提示词…": "系统提示词…",
	索引可用: "索引可用",
	索引异常: "索引异常",
	索引未检查: "索引未检查",
	紧凑: "紧凑",
	紫色: "紫色",
	紫蓝渐变: "紫蓝渐变",
	红色: "红色",
	纯文本: "纯文本",
	"纯色层级更安静，并以清晰实线边界维持长期工作的可读性。": "纯色层级更安静，并以清晰实线边界维持长期工作的可读性。",
	纵向分布: "纵向分布",
	终止进程: "终止进程",
	"终止进程 ": "终止进程 ",
	"终止这个回合？": "终止这个回合？",
	结束: "结束",
	结果: "结果",
	"结果上限 limit（默认 5，1-20）": "结果上限 limit（默认 5，1-20）",
	结论: "结论",
	"给 Sunday 发送任务...": "给 Sunday 发送任务...",
	"继承全局策略：{0}": "继承全局策略：{0}",
	"继承全局（当前：{0}）": "继承全局（当前：{0}）",
	继续编辑: "继续编辑",
	"继续问…": "继续问…",
	绿色: "绿色",
	缓存: "缓存",
	缓存命中率: "缓存命中率",
	"缓存（": "缓存（",
	编排: "编排",
	编辑: "编辑",
	"编辑 {0}": "编辑 {0}",
	编辑供应商: "编辑供应商",
	编辑右侧面板布局: "编辑右侧面板布局",
	编辑定时任务: "编辑定时任务",
	编辑工作流: "编辑工作流",
	编辑待发送内容: "编辑待发送内容",
	编辑文件: "编辑文件",
	编辑条件: "编辑条件",
	编辑模型: "编辑模型",
	编辑消息: "编辑消息",
	编辑笔记全文: "编辑笔记全文",
	编辑节点: "编辑节点",
	编辑连线条件: "编辑连线条件",
	缩小: "缩小",
	缺少可打开的附件标识: "缺少可打开的附件标识",
	缺少可读取的文本路径: "缺少可读取的文本路径",
	网关: "网关",
	网关运行中: "网关运行中",
	网格吸附已关闭: "网格吸附已关闭",
	网格吸附已开启: "网格吸附已开启",
	网格视图: "网格视图",
	置顶: "置顶",
	置顶会话: "置顶会话",
	置顶项目: "置顶项目",
	翻译: "翻译",
	耗时: "耗时",
	"耗时 ": "耗时 ",
	"耗时 {0} s": "耗时 {0} s",
	"耗时 —": "耗时 —",
	聊天: "聊天",
	聚焦选中: "聚焦选中",
	"背景板 / 侧边栏": "背景板 / 侧边栏",
	能力: "能力",
	能力分类: "能力分类",
	"能力的模型。保存到": "能力的模型。保存到",
	自动: "自动",
	自动检查: "自动检查",
	"自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。": "自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。",
	"自动继续的内存阈值（GB）": "自动继续的内存阈值（GB）",
	"自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。": "自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。",
	"自动（内置声明）": "自动（内置声明）",
	自定义: "自定义",
	"自定义工作流节点。": "自定义工作流节点。",
	自定义接口: "自定义接口",
	自定义证书: "自定义证书",
	自检: "自检",
	"自迭代 (loop)": "自迭代 (loop)",
	节流: "节流",
	"节流 {0}s": "节流 {0}s",
	节点: "节点",
	"节点 {0} · 画布元素 {1}": "节点 {0} · 画布元素 {1}",
	节点分类: "节点分类",
	节点参数: "节点参数",
	节点已对齐: "节点已对齐",
	节点已横向分布: "节点已横向分布",
	节点已纵向分布: "节点已纵向分布",
	节点标题: "节点标题",
	节点目录: "节点目录",
	节点目录筛选: "节点目录筛选",
	"英 {0} 美 {1}": "英 {0} 美 {1}",
	"范围 {0}-{1} 行": "范围 {0}-{1} 行",
	"范围进度，尚未独立评估": "范围进度，尚未独立评估",
	草稿: "草稿",
	莓果渐变: "莓果渐变",
	"莓紫、灰蓝与青绿的横向渐变。": "莓紫、灰蓝与青绿的横向渐变。",
	获取网页: "获取网页",
	"获取网页 {0}": "获取网页 {0}",
	蓝色: "蓝色",
	行: "行",
	行内代码: "行内代码",
	"补齐缺少的端口（": "补齐缺少的端口（",
	表单说明: "表单说明",
	表格: "表格",
	覆盖: "覆盖",
	"规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。": "规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。",
	视图切换: "视图切换",
	视觉: "视觉",
	角色: "角色",
	角色分配: "角色分配",
	解释: "解释",
	解锁: "解锁",
	"解锁 {0}": "解锁 {0}",
	触发器: "触发器",
	"触发器 ID 不能为空": "触发器 ID 不能为空",
	"触发器 ID 已存在：{0}": "触发器 ID 已存在：{0}",
	"触发器 {0}": "触发器 {0}",
	触发器列表: "触发器列表",
	"触发器已保存。": "触发器已保存。",
	触发器激活: "触发器激活",
	触发器类型: "触发器类型",
	计划: "计划",
	计划更新失败: "计划更新失败",
	"计划：{0} 步": "计划：{0} 步",
	"让 agent 完成的目标…": "让 agent 完成的目标…",
	记忆: "记忆",
	记忆名称: "记忆名称",
	"记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。": "记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。",
	记忆档位: "记忆档位",
	记忆续跑: "记忆续跑",
	记忆编辑: "记忆编辑",
	记忆阅读: "记忆阅读",
	设为预设首选: "设为预设首选",
	设备: "设备",
	"设备 ID": "设备 ID",
	设备与工作环境: "设备与工作环境",
	设置: "设置",
	设置分区: "设置分区",
	"设置界面语言、网络连接与运行偏好。": "设置界面语言、网络连接与运行偏好。",
	设计创作: "设计创作",
	询问: "询问",
	该供应商下还没有模型: "该供应商下还没有模型",
	该目录已在列表中: "该目录已在列表中",
	该组还没有模型: "该组还没有模型",
	该连线已经存在: "该连线已经存在",
	详情: "详情",
	详细调整: "详细调整",
	"说明何时使用，供 Agent 检索": "说明何时使用，供 Agent 检索",
	"说明希望如何处理…": "说明希望如何处理…",
	"请先保存工作流并解决冲突，再激活触发器": "请先保存工作流并解决冲突，再激活触发器",
	"请先新增供应商，再添加模型": "请先新增供应商，再添加模型",
	"请先添加供应商/模型（设置 → 模型与供应商）": "请先添加供应商/模型（设置 → 模型）",
	请先选择会话: "请先选择会话",
	请先选择供应商: "请先选择供应商",
	"请填写必填输入：{0}": "请填写必填输入：{0}",
	请求中: "请求中",
	"请输入有效 JSON：{0}": "请输入有效 JSON：{0}",
	"请选择完整归档的保存位置…": "请选择完整归档的保存位置…",
	读: "读",
	"读取 {0}": "读取 {0}",
	读取中: "读取中",
	"读取中…": "读取中…",
	"读取了{0}个文件": "读取了{0}个文件",
	"读取了{0}个文件…": "读取了{0}个文件…",
	读取失败: "读取失败",
	读取定时任务失败: "读取定时任务失败",
	读取文件: "读取文件",
	"读取运行记录…": "读取运行记录…",
	"读取运行详情失败：{0}": "读取运行详情失败：{0}",
	调度: "调度",
	调度方式: "调度方式",
	调整主界面: "调整主界面",
	"调整内容区的信息密度。": "调整内容区的信息密度。",
	调整子代理面板宽度: "调整子代理面板宽度",
	调整宽高: "调整宽高",
	调整控件: "调整控件",
	"调整此任务的执行时间、指令和运行方式。": "调整此任务的执行时间、指令和运行方式。",
	调整背景板和侧边栏: "调整背景板和侧边栏",
	调整输入栏: "调整输入栏",
	调用: "调用",
	"调用 MCP 工具": "调用 MCP 工具",
	"调用一次 (none)": "调用一次 (none)",
	"调用了{0}个工具": "调用了{0}个工具",
	"调用另一个工作流。": "调用另一个工作流。",
	"调用智能体执行任务，可按需使用工具。": "调用智能体执行任务，可按需使用工具。",
	"象牙白与石墨灰的纯色主题。": "象牙白与石墨灰的纯色主题。",
	负责人: "负责人",
	"负责逐工具能力边界，不在这里重复配置。": "负责逐工具能力边界，不在这里重复配置。",
	账号: "账号",
	账号与设备: "账号与设备",
	"账号绑定命令将在桌面 Tauri 运行时启用。": "账号绑定命令将在桌面 Tauri 运行时启用。",
	资料: "资料",
	"资料 / 记忆 / 方案 — 一个入口三块内容。": "资料 / 记忆 / 方案 — 一个入口三块内容。",
	资料库: "库",
	"资料库 › {0}": "库 › {0}",
	"资料库 › 资料": "库 › 资料",
	资料库分区: "库分区",
	资料库还是空的: "库还是空的",
	资源: "资源",
	超时: "超时",
	"超时 ": "超时 ",
	"超时 (秒)": "超时 (秒)",
	"超时秒数 timeout": "超时秒数 timeout",
	"超时（秒）": "超时（秒）",
	超高: "超高",
	跟随系统: "跟随系统",
	"跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。": "跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。",
	"跨项目查找会话、消息、方案与文件。": "跨项目查找会话、消息、方案与文件。",
	路径: "路径",
	跳过: "跳过",
	转到注册: "转到注册",
	转换: "转换",
	"转换（兼容）": "转换（兼容）",
	轻: "轻",
	输入: "输入",
	"输入你的回答…": "输入你的回答…",
	"输入关键词搜索任务、插件或文件": "输入关键词搜索任务、插件或文件",
	"输入内容...": "输入内容...",
	"输入内容…": "输入内容…",
	"输入必须是对象：{0}": "输入必须是对象：{0}",
	"输入必须是数字：{0}": "输入必须是数字：{0}",
	"输入必须是数组：{0}": "输入必须是数组：{0}",
	输入栏: "输入栏",
	"输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。": "输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。",
	输入端口: "输入端口",
	输入端口类型: "输入端口类型",
	输入输出: "输入输出",
	输出: "输出",
	"输出工作流结果。": "输出工作流结果。",
	"输出格式（文本说明，可选）": "输出格式（文本说明，可选）",
	输出端口: "输出端口",
	"输出端口 = JSON 字段（强制 JSON 输出）": "输出端口 = JSON 字段（强制 JSON 输出）",
	"输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）": "输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）",
	"输出端口 = 给同名变量赋值": "输出端口 = 给同名变量赋值",
	输出端口类型: "输出端口类型",
	"输出预设的常量值。": "输出预设的常量值。",
	过程: "过程",
	过程图标颜色: "过程图标颜色",
	过程图标颜色十六进制值: "过程图标颜色十六进制值",
	运行: "运行",
	"运行 ID": "运行 ID",
	"运行 {0}": "运行 {0}",
	"运行一条 Shell 命令。": "运行一条 Shell 命令。",
	运行与适配: "运行与适配",
	运行中: "运行中",
	"运行中…": "运行中…",
	运行事件: "运行事件",
	运行历史: "运行历史",
	运行命令: "运行命令",
	运行失败: "运行失败",
	"运行失败：{0}": "运行失败：{0}",
	运行整个工作流: "运行整个工作流",
	运行时: "运行时",
	运行模式: "运行模式",
	运行模式与权限参数: "运行模式与权限参数",
	"运行模式与权限：{0} · {1}": "运行模式与权限：{0} · {1}",
	运行模式选项: "运行模式选项",
	运行此节点: "运行此节点",
	运行状态: "运行状态",
	运行策略: "运行策略",
	运行结果: "运行结果",
	"运行节点…": "运行节点…",
	运行详情: "运行详情",
	运行输入: "运行输入",
	"运行输入必须是 JSON 对象": "运行输入必须是 JSON 对象",
	"运行输入（JSON，可选）": "运行输入（JSON，可选）",
	运行进度: "运行进度",
	运行链路: "运行链路",
	返回: "返回",
	返回主会话: "返回主会话",
	返回主界面: "返回主界面",
	返回会话: "返回会话",
	"返回会话（Esc）": "返回会话（Esc）",
	返回列表: "返回列表",
	返回学习: "返回学习",
	返回对话: "返回对话",
	返回登录: "返回登录",
	还原: "还原",
	"还没有 Markdown 笔记。": "还没有 Markdown 笔记。",
	还没有供应商: "还没有供应商",
	"还没有内容。": "还没有内容。",
	还没有定时任务: "还没有定时任务",
	还没有工作模式: "还没有工作模式",
	"还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。": "还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。",
	"还没有摘要 — 打开写第一段。": "还没有摘要 — 打开写第一段。",
	"还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。": "还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。",
	还没有方案: "还没有方案",
	还没有模型组: "还没有模型组",
	还没有运行历史: "还没有运行历史",
	"还没有运行记录。": "还没有运行记录。",
	还没有项目有记忆: "还没有项目有记忆",
	这一层还没有文件: "这一层还没有文件",
	这一行没有可打开的文件路径: "这一行没有可打开的文件路径",
	"这个子代理还没有产生过程记录。": "这个子代理还没有产生过程记录。",
	这个文件夹还是空的: "这个文件夹还是空的",
	"这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。": "这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。",
	"这个文件夹里还没有记忆文件。": "这个文件夹里还没有记忆文件。",
	这个模式可以使用全部工具: "这个模式可以使用全部工具",
	"这个状态下暂无任务。": "这个状态下暂无任务。",
	"这个状态下暂无方案。": "这个状态下暂无方案。",
	"这个账号还没有已登记设备。": "这个账号还没有已登记设备。",
	"这些信息用于连接模型服务。": "这些信息用于连接模型服务。",
	"这些设置只作为新会话的起点，不会静默改变已经运行的任务。": "这些设置只作为新会话的起点，不会静默改变已经运行的任务。",
	这条消息没有可用的回合: "这条消息没有可用的回合",
	"这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。": "这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。",
	这片记忆还是空的: "这片记忆还是空的",
	"这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。": "这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。",
	这里还没有子文件夹: "这里还没有子文件夹",
	进度: "进度",
	进程日志: "进程日志",
	进行中: "进行中",
	进阶: "进阶",
	"远程图片仅在 Study 中显示：{0}": "远程图片仅在 Study 中显示：{0}",
	"远端工作流有更新，请处理冲突": "远端工作流有更新，请处理冲突",
	"连接一个可用的模型服务。": "连接一个可用的模型服务。",
	连接信息: "连接信息",
	连接异常: "连接异常",
	连线已更新: "连线已更新",
	迭代模式: "迭代模式",
	"追加加载的文件（addition）": "追加加载的文件（addition）",
	退出条件: "退出条件",
	"退出条件（Python 表达式）": "退出条件（Python 表达式）",
	"退出码 ": "退出码 ",
	"退出码 {0}": "退出码 {0}",
	退出账号: "退出账号",
	"适合长时间处理任务与配置。": "适合长时间处理任务与配置。",
	适应画布: "适应画布",
	"选中文字后右键，即可解释、询问或翻译。": "选中文字后右键，即可解释、询问或翻译。",
	选填: "选填",
	"选填，如限速、用途、注意事项等": "选填，如限速、用途、注意事项等",
	"选填，留空时使用模型 ID": "选填，留空时使用模型 ID",
	选择: "选择",
	"选择 {0}": "选择 {0}",
	"选择一个工作目录，系统会为项目准备基础配置。": "选择一个工作目录，系统会为项目准备基础配置。",
	"选择一个已登记的项目继续工作。": "选择一个已登记的项目继续工作。",
	"选择主题随系统变化、固定在一个模式，或按时段自动切换。": "选择主题随系统变化、固定在一个模式，或按时段自动切换。",
	选择供应商: "选择供应商",
	"选择官方模板，或手动填写服务信息。": "选择官方模板，或手动填写服务信息。",
	选择工作模式: "选择工作模式",
	"选择工作流 JSON 文件": "选择工作流 JSON 文件",
	选择工作环境: "选择工作环境",
	选择已有照片: "选择已有照片",
	选择已登记项目: "选择已登记项目",
	"选择应用界面的显示语言。不会更改对话内容或模型的回答语言。": "选择应用界面的显示语言。不会更改对话内容或模型的回答语言。",
	选择或填写项目地址: "选择或填写项目地址",
	"选择或输入模型 ID": "选择或输入模型 ID",
	选择模型: "选择模型",
	选择模型组: "选择模型组",
	"选择模板后，按官方页面申请 API key；免费模型通常有额度或容量限制。": "选择模板后，按官方页面申请 API key；免费模型通常有额度或容量限制。",
	选择此目录: "选择此目录",
	选择目录: "选择目录",
	选择要放入: "选择要放入",
	选择附件来源: "选择附件来源",
	选择项目: "选择项目",
	"选择项目后查看成果库。": "选择项目后查看成果库。",
	选择项目目录: "选择项目目录",
	透明度: "透明度",
	"逐工具白名单、工具模式与扩展权限分别管理": "逐工具白名单、工具模式与扩展权限分别管理",
	通用: "通用",
	通用文件夹: "通用文件夹",
	通过对话创建笔记: "通过对话创建笔记",
	速率限制: "速率限制",
	"遍历数组 (map)": "遍历数组 (map)",
	配图: "配图",
	配对新设备: "配对新设备",
	配置: "配置",
	"配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。": "配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。",
	"配置任务的执行时间、指令和运行方式。": "配置任务的执行时间、指令和运行方式。",
	配置完成: "配置完成",
	配置文件: "配置文件",
	配置模型供应商: "配置模型供应商",
	采用远端版本: "采用远端版本",
	重做: "重做",
	"重做（Ctrl/Cmd+Shift+Z）": "重做（Ctrl/Cmd+Shift+Z）",
	重合区域: "重合区域",
	"重合区域：": "重合区域：",
	重命名: "重命名",
	"重命名会话 {0}": "重命名会话 {0}",
	"重命名失败：{0}": "重命名失败：{0}",
	重命名方案: "重命名方案",
	重命名模型组: "重命名模型组",
	重新下载: "重新下载",
	重新显示首次引导: "重新显示首次引导",
	重新检查: "重新检查",
	重试: "重试",
	重试中: "重试中",
	"重试中 {0}/{1}": "重试中 {0}/{1}",
	重试次数: "重试次数",
	重连中: "重连中",
	钩子: "钩子",
	钩子·已信任: "钩子·已信任",
	链接: "链接",
	锁定选中内容: "锁定选中内容",
	错误处理: "错误处理",
	错误输出: "错误输出",
	"长期驻留（轮次结束后继续运行）": "长期驻留（轮次结束后继续运行）",
	问题: "问题",
	间隔: "间隔",
	间隔秒数: "间隔秒数",
	"间隔触发器需要 every_seconds": "间隔触发器需要 every_seconds",
	"阈值需要是 0.5 到 1024 之间的数字（GB）": "阈值需要是 0.5 到 1024 之间的数字（GB）",
	"队列 ID": "队列 ID",
	队列与历史: "队列与历史",
	队列优先级: "队列优先级",
	"队列刷新失败：{0}": "队列刷新失败：{0}",
	队列视图: "队列视图",
	队列运行详情: "队列运行详情",
	防抖: "防抖",
	"防抖 {0}s": "防抖 {0}s",
	防抖模式: "防抖模式",
	附件: "附件",
	"附件上传失败：{0}": "附件上传失败：{0}",
	附件预览失败: "附件预览失败",
	附件预览已读取: "附件预览已读取",
	降级输出: "降级输出",
	降级输出端口: "降级输出端口",
	降级默认值: "降级默认值",
	"限速 {0}/{1}s": "限速 {0}/{1}s",
	随轮次结束清理: "随轮次结束清理",
	隐藏已移除: "隐藏已移除",
	"雾蓝到奶油白的浅色渐变。": "雾蓝到奶油白的浅色渐变。",
	需压缩: "需压缩",
	需确认: "需确认",
	需要你确认: "需要你确认",
	"需要你确认，共 {0} 项": "需要你确认，共 {0} 项",
	青色: "青色",
	面板: "面板",
	音视频: "音视频",
	顶对齐: "顶对齐",
	项: "项",
	项目: "项目",
	"项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。": "项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。",
	"项目作用域的元信息与 AGENTS.md 指令。": "项目作用域的元信息与 AGENTS.md 指令。",
	"项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。": "项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。",
	"项目列表不可用，无法进入项目记忆": "项目列表不可用，无法进入项目记忆",
	项目名称: "项目名称",
	项目图标: "项目图标",
	项目图标与颜色: "项目图标与颜色",
	项目地址: "项目地址",
	项目外观: "项目外观",
	"项目将保存在当前设备。": "项目将保存在当前设备。",
	"项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。": "项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。",
	项目成果库: "项目成果库",
	项目操作: "项目操作",
	"项目文件和自动生成的 AGENTS.md 将存放在此目录。": "项目文件和自动生成的 AGENTS.md 将存放在此目录。",
	项目目录: "项目目录",
	项目规则: "项目规则",
	项目记忆: "项目记忆",
	"项目记忆按项目归档 — 先选一个项目，再整理它的记忆。": "项目记忆按项目归档 — 先选一个项目，再整理它的记忆。",
	项目设置: "项目设置",
	项目设置分区: "项目设置分区",
	"项目里进出的文件 — 用户上传、中间产物与最终产物。": "项目里进出的文件 — 用户上传、中间产物与最终产物。",
	项目颜色: "项目颜色",
	"项；文件本身不会被删除。": "项；文件本身不会被删除。",
	预览: "预览",
	"预览 {0}": "预览 {0}",
	预览排版: "预览排版",
	预设颜色: "预设颜色",
	预设首选: "预设首选",
	频率: "频率",
	颜色: "颜色",
	"颜色节点、透明度与界面密度": "颜色节点、透明度与界面密度",
	风险扫描: "风险扫描",
	首个执行: "首个执行",
	首次任务: "首次任务",
	首次使用引导: "首次使用引导",
	验证: "验证",
	验证未通过: "验证未通过",
	高: "高",
	"高危命令默认需要运行前确认（自动批准模式除外）。": "高危命令默认需要运行前确认（自动批准模式除外）。",
	高级工具白名单: "高级工具白名单",
	高级设置: "高级设置",
	高级调整: "高级调整",
	"高级适配 JSON": "高级适配 JSON",
	"高级适配 JSON 必须是对象": "高级适配 JSON 必须是对象",
	默认: "默认",
	"默认值（空=哨兵跳过）": "默认值（空=哨兵跳过）",
	"默认内核 provider": "默认内核 provider",
	默认多模态解析模型: "默认多模态解析模型",
	"默认审批策略保存失败，已回滚：{0}": "默认审批策略保存失败，已回滚：{0}",
	默认搜索内核: "默认搜索内核",
	默认模型: "默认模型",
	"（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。 外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。": "（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。 外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。",
	"（支持": "（支持",
	"（无）": "（无）",
	"（日志为空）": "（日志为空）",
	"（暂无日志输出）": "（暂无日志输出）",
	"（检查网络后重试）": "（检查网络后重试）",
	"（空指令）": "（空指令）",
	"（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。",
	"（还没有内容）": "（还没有内容）",
	"（还没有摘要）": "（还没有摘要）",
	"（默认 work_root）": "（默认 work_root）",
	"（默认模型）": "（默认模型）",
	"＋ 新增模型": "＋ 新增模型",
	"＋ 新建供应商": "＋ 新建供应商",
	"＋ 追加文件": "＋ 追加文件",
	"，且无法恢复。": "，且无法恢复。",
	"，但没有适用于本平台的安装包（可到发布页查看）": "，但没有适用于本平台的安装包（可到发布页查看）",
	"，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：": "，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：",
	"，移动端为应用私有技能目录）。": "，移动端为应用私有技能目录）。",
	"，里面的条目也会一起删掉": "，里面的条目也会一起删掉",
	"：暂无可配置参数": "：暂无可配置参数",
	"thinking.off": "关闭",
	"保存修改？": "保存修改？",
	丢弃修改: "丢弃修改",
	"未能保存，请检查修改后重试。": "未能保存，请检查修改后重试。",
	自动恢复阈值: "自动恢复阈值",
	子代理指南: "子代理指南",
	代理地址: "代理地址",
	直连地址: "直连地址",
	"CA 证书": "CA 证书",
	"请填写必填项并检查输入格式。": "请填写必填项并检查输入格式。",
	"配置已保存，但未能完成同步：{0}": "配置已保存，但未能完成同步：{0}",
	继续运行: "继续运行",
	重试启动: "重试启动",
	"新插件系统（预览）": "新插件系统（预览）",
	"与当前插件页互不影响。这里只验证清单、启停和卸载。": "与当前插件页互不影响。这里只验证清单、启停和卸载。",
	"还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。",
	禁用: "禁用",
	没有声明能力: "没有声明能力",
	"声明错误：{0}": "声明错误：{0}",
	"加载错误 {0}": "加载错误 {0}",
	"卸载 {0}？data 目录会保留。": "卸载 {0}？data 目录会保留。",
	"已卸载 {0}，data 目录保留。": "已卸载 {0}，data 目录保留。",
	会修改数据: "会修改数据",
	"sha256（可选）": "sha256（可选）",
	"{0} 条匹配": "{0} 条匹配",
	"内核（不可替换）": "内核（不可替换）",
	"加载配置中…": "加载配置中…",
	压缩包: "压缩包",
	可替换模块: "可替换模块",
	"字段 {0} 需要合法的 JSON。": "字段 {0} 需要合法的 JSON。",
	"已保存 {0} 的配置。": "已保存 {0} 的配置。",
	"当前环境没有桌面窗口，插件窗口只能在桌面端打开。": "当前环境没有桌面窗口，插件窗口只能在桌面端打开。",
	"打开窗口 {0}": "打开窗口 {0}",
	收起配置: "收起配置",
	"更新（同名替换，data 保留）": "更新（同名替换，data 保留）",
	"查行为表：模块名或片段（如 prompt、plugin_system.host）": "查行为表：模块名或片段（如 prompt、plugin_system.host）",
	查询: "查询",
	没有声明依赖: "没有声明依赖",
	"清单、启停、安装、更新与卸载都在这里。": "清单、启停、安装、更新与卸载都在这里。",
	"确定执行 {0}？": "确定执行 {0}？",
	"确定执行 {0}？该操作会修改数据。": "确定执行 {0}？该操作会修改数据。",
	"自定义配置面板加载失败：{0}": "自定义配置面板加载失败：{0}",
	"这个插件没有可配置项。": "这个插件没有可配置项。",
	筛选文档: "筛选文档",
	"Wiki 目录": "Wiki 目录",
	目录: "目录",
	文档导航: "文档导航",
	没有匹配的文档: "没有匹配的文档",
	没有可用的文档: "没有可用的文档",
	"data 目录会保留": "data 目录会保留",
	"{0} / {1}": "{0} / {1}",
	"{0} 个已启用": "{0} 个已启用",
	"{0} 个插件": "{0} 个插件",
	"{0} 个需要处理": "{0} 个需要处理",
	"依赖：{0}": "依赖：{0}",
	入口: "入口",
	全局: "全局",
	"分屏打开 {0}": "分屏打开 {0}",
	"卸载 {0}": "卸载 {0}",
	"卸载插件？": "卸载插件？",
	启动失败: "启动失败",
	"启用 {0}": "启用 {0}",
	"在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。",
	声明错误: "声明错误",
	复制安装路径: "复制安装路径",
	安全模式已跳过: "安全模式已跳过",
	安装或更新插件: "安装或更新插件",
	安装来源: "安装来源",
	安装来源地址: "安装来源地址",
	已停止: "已停止",
	"已安装 {0}": "已安装 {0}",
	"已更新 {0}": "已更新 {0}",
	"换个关键词，或清除筛选条件。": "换个关键词，或清除筛选条件。",
	"插件代码已更新，重启应用后模块覆盖和全局脚本将生效。": "插件代码已更新，重启应用后模块覆盖和全局脚本将生效。",
	插件配置: "插件配置",
	"搜索插件、能力或路径": "搜索插件、能力或路径",
	收起安装: "收起安装",
	"更新会覆盖同名插件，data 目录会保留。": "更新会覆盖同名插件，data 目录会保留。",
	未声明能力: "未声明能力",
	"本地目录、压缩包或链接，三种来源共用一条流程。": "本地目录、压缩包或链接，三种来源共用一条流程。",
	查询行为表: "查询行为表",
	"模块名或片段（如 prompt、plugin_system.host）": "模块名或片段（如 prompt、plugin_system.host）",
	正在切换: "正在切换",
	正在启动: "正在启动",
	"没有加载错误。": "没有加载错误。",
	没有匹配的插件: "没有匹配的插件",
	没有描述: "没有描述",
	清除筛选: "清除筛选",
	"禁用 {0}": "禁用 {0}",
	等待启动: "等待启动",
	筛选插件: "筛选插件",
	缺失: "缺失",
	行为表查询与加载错误: "行为表查询与加载错误",
	诊断与行为表: "诊断与行为表",
	运行就绪: "运行就绪",
	还没有插件: "还没有插件",
	需要处理: "需要处理",
	"（缺 {0}，可用 pip 安装；不阻止安装）": "（缺 {0}，可用 pip 安装；不阻止安装）",
	自定义配置面板加载失败: "自定义配置面板加载失败",
	无法加载插件: "无法加载插件",
	"检查后台连接后再试一次。": "检查后台连接后再试一次。",
	再试一次: "再试一次",
	"QQ robot": "QQ robot",
	插件页面: "插件页面",
	源代码与许可证: "源代码与许可证",
	"当前显示缓存目录；安装时会重新核对 GitHub 最新发布。": "当前显示缓存目录；安装时会重新核对 GitHub 最新发布。",
	插件市场: "插件市场",
	"从 GitHub 安装插件": "从 GitHub 安装插件",
	插件能力: "插件能力",
	"暂时无法获取市场目录，请检查网络后重试。": "暂时无法获取市场目录，请检查网络后重试。",
	"正在连接插件市场…": "正在连接插件市场…",
	版本暂不可用: "版本暂不可用",
	"独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。": "独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。",
	视频与字幕检索: "视频与字幕检索",
	内容与信息: "内容与信息",
	重新连接: "重新连接",
	每日内容简报: "每日内容简报",
	消息与协作: "消息与协作",
	刷B站: "刷B站",
	"QQ 私聊与群聊": "QQ 私聊与群聊",
	已安装: "已安装",
	"下载并校验中…": "下载并校验中…",
	持久会话: "持久会话",
	消息提醒: "消息提醒",
	暂不可用: "暂不可用",
	changed: "changed",
	有新版本: "有新版本",
	审批与文件投递: "审批与文件投递",
	"插件已安装，可在“已安装”中配置和管理。": "插件已安装，可在“已安装”中配置和管理。",
	"把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。": "把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。",
	"读取视频字幕、整理值得看的内容，生成日报并发送提醒。": "读取视频字幕、整理值得看的内容，生成日报并发送提醒。",
	"Assistant 显示": "Assistant 显示",
	"只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。": "只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。",
	"Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。": "Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。",
	使用消息气泡: "使用消息气泡",
	"自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。": "自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。",
	自动气泡拆分: "自动气泡拆分",
	"显示名称：留空时使用默认名称（Assistant）。": "显示名称：留空时使用默认名称（Assistant）。",
	"例如 Sunday": "例如 Sunday",
	"头像：上传一张图片并调整裁切；留空时显示名称首字母。": "头像：上传一张图片并调整裁切；留空时显示名称首字母。",
	头像: "头像",
	"例如 https://example.com/avatar.png": "例如 https://example.com/avatar.png",
	图层: "图层",
	元素: "元素",
	未分层: "未分层",
	"在「{0}」内": "在「{0}」内",
	父层自动: "父层自动",
	"父层 z={0}": "父层 z={0}",
	"自动层（按文档顺序，后绘制的在上）": "层内自动子层（同一块里按文档顺序，后绘制的在上）",
	关闭编辑器: "关闭编辑器",
	收起面板: "收起面板",
	展开面板: "展开面板",
	编辑模式: "编辑模式",
	"编辑模式已关闭，界面可正常操作。": "编辑模式已关闭，界面可正常操作。",
	不保存修改并退出: "不保存修改并退出",
	"在界面上点选组件，或从下面选择。": "在界面上点选组件，或从下面选择。",
	"正在预览真实界面，修改会立即生效。": "正在预览真实界面，修改会立即生效。",
	属性: "属性",
	"先选择一个组件。": "先选择一个组件。",
	"这个组件是业务入口，只能调整外观，不能移动或隐藏。": "这个组件是业务入口，只能调整外观，不能移动或隐藏。",
	文字颜色: "文字颜色",
	背景颜色: "背景颜色",
	"自动（跟随页面）": "自动（跟随页面）",
	锚点: "锚点",
	横向: "横向",
	纵向: "纵向",
	不锚定: "不锚定",
	横向锚点: "横向锚点",
	纵向锚点: "纵向锚点",
	横向距离: "横向距离",
	纵向距离: "纵向距离",
	"锚点=到父容器某条边的距离，不会小于 0。": "锚点=到父容器某条边的距离，不会小于 0。",
	自定义颜色: "自定义颜色",
	透明: "透明",
	主区域底色: "主区域底色",
	主区域柔和底色: "主区域柔和底色",
	应用底色: "应用底色",
	输入区底色: "输入区底色",
	控件底色: "控件底色",
	背景颜色令牌无效: "背景颜色令牌无效",
	圆角: "圆角",
	间距: "间距",
	字号: "字号",
	层级: "层级",
	"显示/隐藏图层": "显示/隐藏图层",
	"锁定/解锁图层": "锁定/解锁图层",
	"第 {0} 层": "第 {0} 层",
	显示: "显示",
	清除这个组件的修改: "清除这个组件的修改",
	有未发布修改: "有未发布修改",
	已同步: "已同步",
	发布: "发布",
	受保护: "受保护",
	仅外观: "仅外观",
	可编辑: "可编辑",
	"文件不是有效的主题 JSON": "文件不是有效的主题 JSON",
	编辑布局: "编辑布局",
	打开编辑器: "打开编辑器",
	"进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。": "进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。",
	基础样式: "基础样式",
	窄于: "窄于",
	按当前宽度加断点: "按当前宽度加断点",
	删除这个断点: "删除这个断点",
	"正在编辑窄屏覆盖，只影响该宽度以下。": "正在编辑窄屏覆盖，只影响该宽度以下。",
	"正在编辑这一条，只影响它自己。": "正在编辑这一条，只影响它自己。",
	横向位置: "横向位置",
	纵向位置: "纵向位置",
	背景素材: "背景素材",
	选择图片: "选择图片",
	更换图片: "更换图片",
	图片位置: "图片位置",
	图片缩放: "图片缩放",
	拖动九宫格选择图片显示的部分: "拖动九宫格选择图片显示的部分",
	"九宫格就是实际显示的部分，拖动可直接改取景。": "九宫格就是实际显示的部分，拖动可直接改取景。",
	模板样式: "模板样式",
	允许溢出组件: "允许溢出组件",
	"图片过大，单张不能超过 1.5MB": "图片过大，单张不能超过 1.5MB",
	图片读取失败: "图片读取失败",
	对齐与分布: "对齐与分布",
	右对齐: "右对齐",
	垂直居中: "垂直居中",
	底对齐: "底对齐",
	水平分布: "水平分布",
	垂直分布: "垂直分布",
	top: "top",
	right: "right",
	bottom: "bottom",
	left: "left",
	上: "上",
	右: "右",
	下: "下",
	左: "左",
	颜色样式: "颜色样式",
	纯色: "纯色",
	渐变: "渐变",
	玻璃: "玻璃",
	高透: "高透",
	低透: "低透",
	高透玻璃: "高透玻璃",
	低透玻璃: "低透玻璃",
	玻璃样式: "玻璃样式",
	"整个区域换成现成玻璃材质，不再单独调色。": "整个区域换成现成玻璃材质，不再单独调色。",
	适应方式: "适应方式",
	铺满: "铺满",
	完整显示: "完整显示",
	平铺: "平铺",
	拉伸: "拉伸",
	"支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。": "支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。",
	实验性功能: "实验性功能",
	实验性: "实验性",
	"分屏文件预览（实验性）": "分屏文件预览（实验性）",
	"图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。": "图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。",
	玻璃材质: "玻璃材质",
	"开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。": "开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。",
	底色: "底色",
	上传图片: "上传图片",
	缩放: "缩放",
	请选择图片文件: "请选择图片文件",
	"图片不能超过 12 MB": "图片不能超过 12 MB",
	"图片读取失败，请换一张再试": "图片读取失败，请换一张再试",
	"这张图片打不开，请换一张再试": "这张图片打不开，请换一张再试",
	"无法处理这张图片，请换一张再试": "无法处理这张图片，请换一张再试",
	拖动图片调整裁切位置: "拖动图片调整裁切位置",
	"拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。": "拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。",
	头像大小: "头像大小",
	圆角率: "圆角率",
	分组名称: "分组名称",
	"删除分组 {0}": "删除分组 {0}",
	"删除分组？": "删除分组？",
	所属分组: "所属分组",
	按分组筛选: "按分组筛选",
	新建分组: "新建分组",
	核心: "核心",
	移动到分组: "移动到分组",
	管理分组: "管理分组",
	"还没有分组。新建一个，把技能归类到瀑布流的各个分区。": "还没有分组。新建一个，把技能归类到瀑布流的各个分区。",
	"这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。": "这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。",
	重命名分组: "重命名分组",
	按事件筛选: "按事件筛选",
	"这个事件下没有 Hook。切回「全部」看看其他事件。": "这个事件下没有 Hook。切回「全部」看看其他事件。",
	"会话「{0}」已完成，点击打开": "会话「{0}」已完成，点击打开",
	"会话「{0}」执行失败，点击打开": "会话「{0}」执行失败，点击打开",
	打开会话: "打开会话",
	桌宠: "桌宠",
	"展开其余 {0} 项": "展开其余 {0} 项",
	部分文件不存在: "部分文件不存在",
	"调用 {0} 次": "调用 {0} 次",
	尚未调用: "尚未调用",
	"总调用 {0} 次": "总调用 {0} 次"
}, gu = {
	交互内容: "互動內容",
	查看代码: "檢視程式碼",
	"交互内容运行失败，可查看代码或重试": "互動內容執行失敗，可檢視程式碼或重試",
	"交互内容过大，请缩小后重试": "互動內容過大，請縮小後重試",
	"交互内容未能加载，可查看代码或重试": "互動內容未能載入，可檢視程式碼或重試",
	成稿: "成稿",
	编辑成稿: "編輯成稿",
	说明: "說明",
	信息: "資訊",
	提示: "提示",
	注意: "注意",
	警告: "警告",
	" · 依赖保留": "· 依賴保留",
	" · 待审核 {0}": "· 待審核 {0}",
	" 个": " 個",
	" 个记录": "筆記錄",
	" 分组": "分組",
	" 子代理时间线": "子代理時間軸",
	" 时间线": "時間軸",
	" 条": " 筆",
	" 的记录": "的記錄",
	" 输入框": "輸入框",
	"# Sub-agent 委派指南\n在此编写自然语言指令，将注入到主 Agent 系统提示词中…": "# Sub-agent 委派指南 在此編寫自然語言指令，將注入到主 Agent 系統提示詞…",
	"# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…": "# 全域限制 對所有項目生效的指令。專案級 AGENTS.md 會在此基礎上疊加…",
	"# 输入：{0}": "# 輸入：{0}",
	"# 输出：{0}": "# 輸出：{0}",
	"# 项目级约束\n项目专属指令，会叠加在全局约束之上…": "# 專案層級限制 專案專屬指令，會疊加在全域約束之上…",
	"(项目根)": "(項目根)",
	"* 或工具名，多个用 | 分隔": "* 或工具名，多個以 | 分隔",
	"+ 添加节点": "+ 新增節點",
	"+ 添加输入": "+ 新增輸入",
	"+ 添加输出": "+ 新增輸出",
	"+ 输入端口": "+ 輸入端口",
	"+ 输出端口": "+ 輸出端口",
	"AGENTS.md · 移动端全局规则": "AGENTS.md · 行動端全域規則",
	"AGENTS.md 内容": "AGENTS.md 內容",
	"AGENTS.md 已保存": "AGENTS.md 已儲存",
	"AI 创意": "AI 創意",
	"AI 模式": "AI 模式",
	"AI（兼容）": "AI(相容)",
	"API 地址": "API 位址",
	"API 基础 URL": "API 基礎 URL",
	"API 基础 URL 必须与所选供应商一致": "API 基礎 URL 必須與所選供應商一致",
	"API 配置": "API 配置",
	"Agent 保护区域": "Agent 保護區域",
	"Agent 工具": "Agent 工具",
	"Agent 生成": "Agent 生成",
	"Agent 锁定了这段内容": "Agent 鎖定了這段內容",
	"Core App Server 连接失败": "Core App Server 連線失敗",
	"DuckDuckGo 本地代理端口": "DuckDuckGo 本地代理端口",
	"DuckDuckGo 本地代理端口（可选）": "DuckDuckGo 本機代理埠（選用）",
	"Enter 续列表 · Tab 缩进": "Enter 續列表 · Tab 縮排",
	"GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。": "GPL/AGPL 元件以獨立程序運作、倉庫不攜帶程式碼；LamTools 僅依固定 JSON 契約呼叫（詳見 docs/web-search-module.md）。",
	"HTTP 代理": "HTTP 代理",
	"ISO 时间": "ISO 時間",
	"JSON 文件与模板": "JSON 檔案與模板",
	"Linux 直接运行本机命令，不提供 Windows shell 选择。": "Linux 直接執行本機指令，不提供 Windows shell 選擇。",
	"MCP 工具名": "MCP 工具名",
	"MCP 工具名不能为空": "MCP 工具名稱不能為空",
	"Markdown 笔记工作区": "Markdown 筆記型工作區",
	"Python 脚本": "Python 腳本",
	"Python 脚本（兼容）": "Python 腳本(相容)",
	"Python 表达式": "Python 表達式",
	"RAG 不可用": "RAG 不可用",
	"SKILL.md 正文，加载后应遵循的指引": "SKILL.md 正文，載入後應遵循的指引",
	"Study 未启用": "Study 未啟用",
	"Sub Agent 思考模式": "Sub Agent 思考模式",
	"Sub Agent 模型": "Sub Agent 模型",
	"Sunday 工作区": "Sunday 工作區",
	"Sunday 设置": "Sunday 設定",
	"URL 不能为空": "URL 不能為空",
	"Web Search 引擎": "Web Search 引擎",
	"[…截断，仅显示尾部…]\n": "[…截斷，僅顯示尾部…]",
	"^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$": "^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$",
	"^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$": "^子代理\\s+(.+?)\\s+({0})\\s*。 ?\\s*$",
	"at（ISO 时间）": "at（ISO 時間）",
	"baidu（百度，国内可达）": "baidu（百度，國內可達）",
	"bing（必应中文）": "bing（必應中文）",
	"command (Shell 命令)": "command (Shell 指令)",
	"command 不能为空": "command 不能為空",
	"ddg（DuckDuckGo，海外）": "ddg（DuckDuckGo，海外）",
	"hook 失败时阻断执行": "hook 失敗時阻斷執行",
	"hooks.json 内容": "hooks.json 內容",
	"hooks.json 当前无法解析（不是合法 JSON），已取消保存。请先到「原始配置」视图修复后再添加 Hook。": "hooks.json 目前無法解析（非合法 JSON），已取消儲存。請先到「原始設定」視圖修復後再新增 Hook。",
	"http (HTTP 请求)": "http (HTTP 請求)",
	"load_context.jsonc · 移动端全局加载规则": "load_context.jsonc · 行動端全域載入規則",
	"mcp (MCP 工具)": "mcp (MCP 工具)",
	"prompt (内联提示)": "prompt (內嵌提示)",
	"websearch.jsonc 内容": "websearch.jsonc 內容",
	"y = x * 2（输入端口名当变量，给输出端口名赋值）": "y = x * 2（輸入埠名當變量，給予輸出埠名賦值）",
	"{0} {1}": "{0} {1}",
	"{0} {1} {2}": "{0} {1} {2}",
	"{0} {1} 失败{2}": "{0} {1} 失敗{2}",
	"{0} {1} 详情": "{0} {1} 詳情",
	"{0} {1}{2}": "{0} {1}{2}",
	"{0} · 文件保留": "{0} · 檔案保留",
	"{0} · 项目设置": "{0} · 專案設定",
	"{0} › {1}编辑 {2}": "{0} › {1}編輯 {2}",
	"{0} › 编辑 {1}": "{0} › 編輯 {1}",
	"{0} 个工具": "{0} 個工具",
	"{0} 个文件": "{0} 個文件",
	"{0} 个文件 · {1}": "{0} 個檔案 · {1}",
	"{0} 个进程 · {1} 个运行中": "{0} 個程序 · {1} 個運行中",
	"{0} 会话操作": "{0} 會話操作",
	"{0} 分段": "{0} 分段",
	"{0} 分钟前": "{0} 分鐘前",
	"{0} 天前": "{0} 天前",
	"{0} 学习进度 {1}%": "{0} 學習進度 {1}%",
	"{0} 小时前": "{0} 小時前",
	"{0} 开关": "{0} 開關",
	"{0} 成果操作": "{0} 成果操作",
	"{0} 文本预览": "{0} 文字預覽",
	"{0} 文档": "{0} 文檔",
	"{0} 次调用": "{0} 次調用",
	"{0} 段": "{0} 段",
	"{0} 的操作": "{0} 的操作",
	"{0} 的格式工具": "{0} 的格式工具",
	"{0} 的过程": "{0} 的過程",
	"{0} 秒": "{0} 秒",
	"{0} 至 {1}": "{0} 至 {1}",
	"{0} 行": "{0} 行",
	"{0} 详情": "{0} 詳情",
	"{0} 附件操作": "{0} 附件操作",
	"{0} 项 · 文件保留": "{0} 項 · 檔案保留",
	"{0} 项目操作": "{0} 項目操作",
	"{0}/.lam/config/subagent/settings.json": "{0}/.lam/config/subagent/settings.json",
	"{0}/{1} 在线": "{0}/{1} 在線",
	"{0}s 后重试：{1}": "{0}s 後重試：{1}",
	"{0}{1}": "{0}{1}",
	"{0}关闭 {1}": "{0}關閉 {1}",
	"{0}内容": "{0}內容",
	"{0}分": "{0}分",
	"{0}原上下文已保留": "{0}原始上下文已保留",
	"{0}向 {1} 发送消息": "{0}向 {1} 發送訊息",
	"{0}天": "{0}天",
	"{0}小时": "{0}小時",
	"{0}必须是正数": "{0}必須是正數",
	"{0}接收 {1} 的消息": "{0}接收 {1} 的訊息",
	"{0}操作": "{0}操作",
	"{0}月{1}日": "{0}月{1}日",
	"{0}标题": "{0}標題",
	"{0}说明": "{0}說明",
	"{0}运行详情": "{0}運行詳情",
	"{0}颜色节点": "{0}顏色節點",
	"{0}（{1}–{2}）": "{0}（{1}–{2}）",
	"{0}（当前配置）": "{0}（目前配置）",
	"{0}，不可点击": "{0}，不可點擊",
	"{0}，打开子代理面板": "{0}，開啟子代理程式面板",
	"· 优先级": "· 優先權",
	"· 历史": "· 歷史",
	"· 对话": "· 對話",
	"· 将自动添加模板内模型": "· 將自動新增模板內模型",
	"· 已登录": "· 已登入",
	"· 来源：": "· 資料來源：",
	"· 运行": "· 運行",
	通过: "通過",
	"。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 上下文」内编辑。": "。注入順序：先全域約束（.lam/core/config/AGENTS.md），再本文件，兩者相加。全域約束在「設定 → 上下文」內編輯。",
	"「{0}」文件夹里的方案 — 点开读全文，就绪后开工。": "“{0}”資料夾裡的方案 — 點開讀全文，就緒後開工。",
	"」将被删除": "”將被刪除",
	"」将被删除，且无法恢复。": "”將被刪除，且無法恢復。",
	"」文件夹里的方案 — 点开读全文，就绪后开工。": "」資料夾裡的方案 — 點開讀全文，就緒後開工。",
	"」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。": "」資料夾；寫好後就出現在這裡。 方案是一本普通的 Markdown 文檔，你也可以直接新建一篇來寫。",
	"」还有没保存的内容，离开就会丢掉。": "」還有沒保存的內容，離開就會丟掉。",
	"一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。": "一個 Step 是一次模型回應及其後續工具結果；預設保留 0 個 Step，歷史會全部匯總；隨後程式會將最新 20 個使用者指令原文追加為編號的「Recent user messages」段落。令牌預算不足時較早條目會靜默丟棄。",
	"一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务， 你的数据与配置都留在本机。": "一個本地優先的 Agent 工作台：管理會話、記憶與自動化任務， 你的資料與設定都留在本機。",
	一句话说明这个技能的用途: "一句話說明這個技能的用途",
	一次性: "一次性",
	"一次性触发器需要 at 时间": "一次性觸發器需要 at 時間",
	上一步: "上一步",
	上一页附件: "上一頁附件",
	上下文: "上下文",
	"上下文 {0}（{1}）": "上下文 {0}（{1}）",
	"上下文、输出、Temperature 与高级适配": "上下文、輸出、Temperature 與高級適配",
	上下文占用: "情境佔用",
	上下文压缩: "情境壓縮",
	上下文已压缩: "上下文已壓縮",
	上下文窗口: "上下文視窗",
	上下文菜单: "快顯選單",
	"上传中…": "上傳中…",
	上传失败: "上傳失敗",
	"上传失败 {0} 个 — {1}": "上傳失敗 {0} 個 — {1}",
	上传文件: "上傳文件",
	"上传文件，或让助手把要留存的产出归入资料库。": "上傳文件，或請助手把要留存的產出歸入庫。",
	上移: "上移",
	"上移 {0}": "上移 {0}",
	上级目录: "上級目錄",
	上页: "上頁",
	下一个模式: "下一個模式",
	下一页附件: "下一頁附件",
	下次: "下次",
	下移: "下移",
	"下移 {0}": "下移 {0}",
	"下载 {0}%": "下載 {0}%",
	下载中: "下載中",
	"下载中…": "下載中…",
	下载安装包: "下載安裝包",
	"下载完成 100%": "下載完成 100%",
	"下载完成后点击「立即安装」。": "下載完成後點選「立即安裝」。",
	"下载完成后请先退出 Sunday，再运行安装包完成升级。": "下載完成後請先退出 Sunday，再執行安裝包完成升級。",
	下页: "下頁",
	不使用代理的地址: "不使用代理程式的地址",
	不可用: "不可用",
	不归档: "不歸檔",
	不迭代: "不迭代",
	不限: "不限",
	"与运行时的确认通道已断开，恢复连接后才能提交选择。": "與運行時的確認通道已斷開，恢復連線後才能提交選擇。",
	个: "個",
	"个 · 工作流 revision": "個 · 工作流程 revision",
	个产物: "個產物",
	个人: "個人",
	个文件: "個文件",
	个条目: "筆",
	个模型: "模型",
	"个模型，可来自多个供应商": "個模型，可來自多個供應商",
	个节点: "個節點",
	中: "中",
	"中止（默认）": "中止（預設）",
	中继: "中繼",
	"中继.{0}": "中繼.{0}",
	中继点: "中繼點",
	中间产物: "中間產物",
	"中（默认）": "中（預設）",
	"为 {0} 添加第一个模型": "為 {0} 新增第一個模型",
	"为不同工作模式配置模型可用的工具。": "為不同工作模式配置模型可用的工具。",
	"为供应商添加一个可调用的模型。": "為供應商增加一個可呼叫的模型。",
	主导航: "主導航",
	主界面: "主介面",
	主题: "主題",
	"主题会即时同步到当前 Sunday 界面。": "主題會即時同步到目前 Sunday 介面。",
	"主题和密度只影响当前 Sunday 界面。": "主題和密度只影響目前 Sunday 介面。",
	主题预设: "主題預設",
	"之后可在 Sunday 设置中继续添加供应商、模型或调整权限模式。": "之後可在 Sunday 設定中繼續新增供應商、模型或調整權限模式。",
	事件: "事件",
	"事件 · {0}": "事件 · {0}",
	"事件审计（": "事件審計（",
	事件类型: "事件類型",
	"事件类型，如 artifact.changed": "事件類型，如 artifact.changed",
	"事件触发器需要 event_type": "事件觸發器需要 event_type",
	于: "於",
	产品发布: "產品發布",
	产物: "產物",
	人工任务: "人工任務",
	人工任务已提交: "人工任務已提交",
	人工协作: "人工協作",
	人工审批: "人工核准",
	"仅在需要时暴露给 Agent": "僅在需要時暴露給 Agent",
	"仅展示用户、中间产物与产物三类。移除只改变成果库状态，不删除文件。": "僅展示使用者、中間產物與產物三類。移除只改變成果庫狀態，不刪除檔案。",
	"仅支持 .zip 安装包：{0}": "僅支援 .zip 安裝套件：{0}",
	仅用于建立设备信任: "僅用於建立裝置信任",
	从一个新会话开始: "從一個新會話開始",
	"从左侧文件树打开一篇笔记。": "從左側文件樹開啟一篇筆記。",
	"从左侧添加一个模型供应商，开始使用 Sunday。": "從左側新增一個模型供應商，開始使用 Sunday。",
	从当前环境导入: "從目前環境導入",
	从成果库移除: "從成果庫移除",
	"从成果库移除 (": "從成果庫移除 (",
	"从成果库移除 {0}": "從成果庫移除 {0}",
	"从成果库移除？": "從成果庫移除？",
	从收藏移除: "從收藏中移除",
	从此处另开会话: "從此處另開會話",
	从此节点运行: "從此節點運行",
	"从此节点运行…": "從此節點運行…",
	"从第 {0} 行": "從第 {0} 行",
	从设备文件中选择: "從設備檔案中選擇",
	从资料库移除: "從庫移除",
	代码: "代碼",
	代码开发: "程式碼開發",
	任务: "任務",
	"任务 {0}…": "任務 {0}…",
	"任务创建后，这里会显示每次运行的时间与结果。": "任務建立後，這裡會顯示每次運行的時間與結果。",
	任务已处理: "任務已處理",
	任务数量: "任務數量",
	任务标题: "任務標題",
	任务类型: "任務類型",
	"任务类型 {0}": "任務類型 {0}",
	"任务类型“{0}”重复，请保留一条。": "任務類型「{0}」重複，請保留一條。",
	"任务运行中，请先停止任务再分叉": "任務運作中，請先停止任務再分叉",
	"任务运行中，请先停止任务再回退": "任務運作中，請先停止任務再回退",
	"任务运行中，请先停止任务再编辑": "任務運作中，請先停止任務再編輯",
	任务页签: "任務頁籤",
	份方案: "份方案",
	优先级: "優先權",
	"优先级 {0}": "優先權 {0}",
	会参与激活: "會參與激活",
	会话: "會話",
	会话与项目: "會話與項目",
	会话已重命名: "會話已重新命名",
	会话操作: "會話操作",
	会话标题: "會話標題",
	估算: "估算",
	位置: "位置",
	低: "低",
	余烬渐变: "餘燼漸變",
	作为引导发送: "作為引導發送",
	"使用官方模板自动填充连接信息和模型。": "使用官方範本自動填入連接資訊和模型。",
	"使用选定模型生成结果。": "使用選定模型產生結果。",
	"使用默认应用打开？": "使用預設應用程式開啟？",
	"例如 C:\\certs\\root-ca.pem": "例如 C:\\certs\\root-ca.pem",
	"例如 deepseek-v4-flash": "例如 deepseek-v4-flash",
	"例如 http://127.0.0.1:7890": "例如 http://127.0.0.1:7890",
	"例如 localhost,127.0.0.1,::1,.example.com,*.corp.com": "例如 localhost,127.0.0.1,::1,.example.com,*.corp.com",
	"例如：Free": "例如：Free",
	"例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议": "例如：Review 最近 24 小時的提交，總結可能引入的 bug 和修復建議",
	"例如：invoice.created": "例如：invoice.created",
	"例如：quality >= 0.8": "例如：quality >= 0.8",
	"例如：代码审查": "例如：程式碼審查",
	"例如：偏好": "例如：偏好",
	"例如：导出显示进度": "例如：匯出顯示進度",
	"例如：我的供应商": "例如：我的供應商",
	"例如：手机项目": "例如：手機項目",
	"例如：每日同步": "例如：每日同步",
	"例如：用户偏好.md": "例如：用戶偏好.md",
	"例如：迭代计划": "例如：迭代計劃",
	供应商: "供應商",
	供应商列表: "供應商列表",
	供应商名称: "供應商名稱",
	供应商已删除: "供應商已刪除",
	供应商已更新: "供應商已更新",
	供应商已添加: "供應商已新增",
	供应商空状态: "供應商空狀態",
	供应商详情: "供應商詳情",
	供应商配置: "供應商配置",
	依赖: "依賴",
	依赖就绪: "依賴就緒",
	依赖未知: "依賴未知",
	依赖缺失: "依賴缺失",
	侧栏滚动条: "側欄捲軸",
	拖动调整左侧栏宽度: "拖曳調整左側欄寬度",
	便签: "便條",
	"便签.{0}": "便條.{0}",
	保存: "儲存",
	保存中: "保存中",
	"保存中…": "保存中…",
	"保存为所有项目的全局基线；项目可单独覆盖。": "儲存為所有項目的全域基準；項目可單獨覆寫。",
	保存供应商: "保存供應商",
	"保存冲突，请选择处理方式": "儲存衝突，請選擇處理方式",
	"保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。": "儲存衝突：遠端版本已更新。請選擇採用遠端，或保留本地後重試。",
	保存到: "保存到",
	"保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global": "儲存到全域設定 ~/.lam/core/config/subagent/guide.md。項目級配置請在項目設定內編輯。留空保存則恢復為內建預設。 CLI：core subagent guide show/set/edit --scope global",
	"保存到项目配置 {0}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>": "儲存到專案配置 {0}/.lam/config/subagent/guide.md。留空保存則移除項目級配置，回退到繼承的全域 / 內建預設。 CLI：core subagent guide show/set/edit --scope project --work-root <root>",
	"保存到项目配置 {0}/.lam/config/subagent/settings.json。": "儲存到專案配置 {0}/.lam/config/subagent/settings.json。",
	"保存后将移除当前项目覆盖，恢复继承全局策略。": "儲存後將移除目前項目覆蓋，恢復繼承全域策略。",
	"保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。": "儲存後新發起的模型、MCP 與指令呼叫立即按新設定走；已連線的 MCP 服務與已執行的後台指令需重新啟動應用。",
	"保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "保存在此裝置的應用私有 SQLite 配置中。專案級規則請在「專案設定 → 專案」內編輯，兩者會相加註入系統提示字。",
	"保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。": "儲存在此裝置的應用私有 SQLite 配置中，全域規則疊加到本機工作區。",
	"保存失败，修改仍保留在当前编辑器。": "儲存失敗，修改仍保留在目前編輯器中。",
	"保存失败：{0}": "儲存失敗：{0}",
	"保存失败：{0}。你的草稿仍保留，请核对重合区域。": "儲存失敗：{0}。你的草稿仍保留，請檢查重疊區域。",
	"保存失败：笔记已被更新，你的草稿仍保留。": "儲存失敗：筆記已更新，你的草稿仍保留。",
	保存工作流: "儲存工作流程",
	"保存工作流（有未保存修改）": "儲存工作流程（有未儲存修改）",
	保存并切换: "儲存並切換",
	保存并继续: "保存並繼續",
	保存成员: "保存會員",
	保存模型: "保存模型",
	保存触发器: "儲存觸發器",
	保存配置: "儲存配置",
	保持电脑运行: "維持電腦運作",
	"保留最近的 Step": "保留最近的 Step",
	保留本地修改并用远端版本号重试保存: "保留本地修改並以遠端版本號重試保存",
	保留本地并重试: "保留本地並重試",
	信任: "信任",
	修改于: "修改於",
	"修改后需重启后端生效。": "修改後需重新啟動後端生效。",
	"修改范围：原 {0} 行起，新 {1} 行起": "修改範圍：原 {0} 行起，新 {1} 行起",
	候选结论: "候選結論",
	值: "值",
	"停止失败：{0}": "停止失敗：{0}",
	停止工作流: "停止工作流程",
	停止运行: "停止運行",
	"停止运行（子代理仍在运行）": "停止運作（子代理仍在執行）",
	停用: "停用",
	"停用失败：{0}": "停用失敗：{0}",
	允许工作目录外: "允許工作目錄外",
	允许手机控制这台电脑: "讓手機控制這台電腦",
	允许访问工作目录以外: "允許存取工作目錄以外",
	"允许读写工作目录之外的路径。": "允許讀寫工作目錄之外的路徑。",
	先保存工作流再排队: "先保存工作流程再排隊",
	先保存工作流再运行: "先保存工作流程再運行",
	先在左侧选择一个项目: "先在左側選擇一個項目",
	"先在左侧选择一个项目 — 资料库跟随项目。": "先在左側選擇一個項目 — 庫跟隨項目。",
	"先在左侧选择一个项目 — 资料库跟随项目文件夹。": "先在左側選擇一個項目 — 庫跟隨專案資料夾。",
	"先提供背景方向，其他区域可继续单独调整。": "先提供背景方向，其他區域可繼續單獨調整。",
	"先用 read_file 读回这份方案（它在当前项目之外，读到它需要你先申请访问批准），对照仓库现状核对需求与步骤，有出入的地方先记下结论；": "先用 read_file 讀回這份方案（它在當前項目之外，讀到它需要你先申請訪問批准），對照倉庫現狀核對需求與步驟，有出入的地方先記下結論；",
	"先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；": "先用 read_file 讀回這份方案，對照倉庫現狀核對需求與步驟，有出入的地方先記下結論並更新方案文件；",
	先进入一个项目: "先進入一個項目",
	"先进入一个项目，再操作它的记忆": "先進入一個項目，再操作它的記憶",
	先选一个工作目录: "先選一個工作目錄",
	"克制的中性灰阶。": "克制的中性灰階。",
	"全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。": "全域上下文。注入順序：全域 AGENTS.md（優先權 5）→ 專案 AGENTS.md（10）；load_context 的 addition/except 全域疊加到每個工作區。",
	全局上下文加载: "全域上下文載入",
	"全局基线适用于所有项目；项目可按同名任务类型覆盖。": "全域基準適用於所有項目；項目可依同名任務類型覆寫。",
	"全局搜索：跨项目查找会话、消息与学习资料。": "全域搜尋：跨專案尋找會話、訊息與學習資料。",
	全局约束: "全域約束",
	"全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 {0} 条。": "全域規則作為基準；這裡只編輯項目覆蓋，同名任務類型以項目規則為準。當前合併後 {0} 條。",
	全局记忆: "全域記憶",
	"全应用的出口流量走哪里，以及它们信任哪个根证书。": "全應用程式的出口流量走哪裡，以及它們信任哪一個根憑證。",
	全选: "全選",
	全部: "全部",
	全部删除: "全部刪除",
	全部工具: "全部工具",
	全部工具可用: "全部工具可用",
	全部状态: "全部狀態",
	全部类型: "全部類型",
	全部角色: "全部角色",
	公式: "公式",
	"六位数字码 5 分钟内有效且只能使用一次": "六位數位碼 5 分鐘內有效且只能使用一次",
	"共 {0} 个 · 已信任 {1}{2}": "共 {0} 個 · 已信任 {1}{2}",
	"共 {0} 个 · 已启用 {1}": "共 {0} 個 · 已啟用 {1}",
	关于与更新: "關於與更新",
	关系: "關係",
	关系图: "關係圖",
	关系图例: "關係圖例",
	关系图加载中: "關係圖載入中",
	关联: "關聯",
	关闭: "關閉",
	关闭并保留草稿: "關閉並保留草稿",
	"恢复默认？": "恢復預設？",
	"将清除已发布的主题与当前草稿，无法撤销。": "將清除已發佈的主題與目前草稿，無法復原。",
	"主题文件过大，请检查是否误选了其他文件": "主題檔案過大，請確認是否誤選了其他檔案",
	"关闭 Sub Agent": "關閉 Sub Agent",
	"关闭 {0} 失败": "關閉 {0} 失敗",
	"关闭了 {0}": "關閉了 {0}",
	"关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。": "關閉後工具從工具集移除；啟用但 API 位址為空時，呼叫會傳回「未配置生圖 API」。",
	关闭工作流标签: "關閉工作流程標籤",
	"关闭提示：{0}": "關閉提示：{0}",
	关闭文本预览: "關閉文字預覽",
	关闭网格吸附: "關閉網格吸附",
	关闭节点目录: "關閉節點目錄",
	"关闭设置？": "關閉設定？",
	关闭详情: "關閉詳情",
	关闭详细调整: "關閉詳細調整",
	关闭配对码: "關閉配對碼",
	关闭面板: "關閉面板",
	关闭预览: "關閉預覽",
	其他: "其他",
	其他处理方式: "其他處理方式",
	"其余时间用另一个模式；跨天时段同样有效。": "其餘時間用另一個模式；跨天時段同樣有效。",
	兼容: "相容",
	"兼容旧版 AI 节点。": "相容於舊版 AI 節點。",
	"兼容旧版 Python 脚本节点。": "相容於舊版 Python 腳本節點。",
	"兼容旧版分支节点。": "相容於舊版分支節點。",
	"兼容旧版转换节点。": "相容於舊版轉換節點。",
	内存中断自动续跑: "記憶體中斷自動續跑",
	内容宽度: "內容寬度",
	"内容（content）": "內容（content）",
	内核配置: "核心配置",
	内置: "內置",
	内置默认: "內建默認",
	"内置：": "內建：",
	写: "寫",
	"写下想法…": "寫下想法…",
	"写下注释…": "寫下註解…",
	"写点什么，助手下次就会读到它。": "寫點什麼，助手下次就會讀到它。",
	"决定工具执行前是否需要你确认。": "決定工具執行前是否需要你確認。",
	"决定模型是否接收图片，以及是否启用推理参数。": "決定模型是否接收圖片，以及是否啟用推理參數。",
	"准备开干！": "準備開乾！",
	几号: "幾號",
	出错: "出錯",
	分层: "分層",
	"分支 {0}": "分支 {0}",
	"分支（兼容）": "分支(兼容)",
	分段: "分段",
	分组: "分組",
	"分组.{0}": "分組.{0}",
	分组键: "分組鍵",
	切换侧栏: "切換側欄",
	"切换到 ": "切換到",
	"切换前要如何处理当前草稿？": "切換前要如何處理目前草稿？",
	切换右侧栏: "切換右側欄",
	切换模式: "切換模式",
	"切换模式，当前 {0}": "切換模式，目前為 {0}",
	"列出 {0}": "列出 {0}",
	列出目录: "列出目錄",
	列表视图: "清單視圖",
	刚刚: "剛剛",
	刚刚打开: "剛打開",
	创建: "創建",
	"创建 {0}": "建立 {0}",
	"创建一个模型组来整理所有供应商下的模型。": "建立一個模型組來整理所有供應商下的模型。",
	创建中: "創建中",
	"创建中…": "創建中…",
	创建了: "創建了",
	创建你的第一个文件夹: "建立你的第一個資料夾",
	创建分组来整理常用模型: "建立分組來整理常用模型",
	"创建失败：{0}": "建立失敗：{0}",
	创建定时任务: "建立定時任務",
	创建技能: "創建技能",
	创建文件: "建立文件",
	创建文件夹: "建立資料夾",
	"创建文件夹，整理资料库中的方案。": "建立資料夾，整理庫中的方案。",
	创建项目: "建立項目",
	删: "刪",
	删除: "刪除",
	"删除 ": "刪除",
	"删除 Hook？": "刪除 Hook？",
	"删除 {0}": "刪除 {0}",
	"删除 {0} 行": "刪除 {0} 行",
	"删除会话及历史？": "刪除會話及歷史？",
	"删除供应商及其模型配置？": "刪除供應商及其模型配置？",
	删除全部队列项和历史: "刪除全部佇列項目和歷史",
	删除内容: "刪除內容",
	"删除子代理 ": "刪除子代理",
	删除容器及其内容: "刪除容器及其內容",
	删除已结束历史: "刪除已結束歷史",
	删除待发送内容: "刪除待傳送內容",
	"删除技能 {0}": "刪除技能 {0}",
	"删除技能及目录？": "刪除技能及目錄？",
	删除文件夹: "刪除資料夾",
	"删除文件夹（含里面全部条目）": "刪除資料夾（含裡面全部條目）",
	删除方案: "刪除方案",
	删除标记: "刪除標記",
	"删除模型组（模型保留）？": "刪除模型組（模型保留）？",
	"删除模型配置？": "刪除模型配置？",
	删除此消息及之后内容: "刪除此訊息及之後內容",
	删除此轮及之后内容: "刪除此輪及之後內容",
	删除组: "刪除群組",
	"删除角色分配 {0}": "刪除角色分配 {0}",
	删除记忆: "刪除記憶",
	删除连线: "刪除連線",
	"删除选中元素（{0}）": "刪除選取元素（{0}）",
	删除项目: "刪除項目",
	"删除项目及会话记录？": "刪除項目及會話記錄？",
	刷新: "重新整理",
	"刷新中…": "刷新中…",
	刷新人工任务: "刷新人工任務",
	刷新成果库: "刷新成果庫",
	刷新激活状态: "刷新啟動狀態",
	刷新笔记文件树: "刷新筆記檔樹",
	刷新进程列表: "刷新進程列表",
	刷新队列: "刷新佇列",
	前置: "前置",
	剪切: "剪切",
	加入队列: "加入隊列",
	加粗: "加粗",
	"加载 {0} 失败：{1}": "載入 {0} 失敗：{1}",
	加载中: "載入中",
	"加载中...": "載入中...",
	"加载中…": "載入中…",
	"加载失败：": "載入失敗：",
	"加载失败：{0}": "載入失敗：{0}",
	加载技能: "載入技能",
	"加载技能 · {0}": "載入技能 · {0}",
	加载类型: "載入類型",
	助手回复: "助理回复",
	勾选后从成果库移除: "勾選後從成果庫移除",
	匹配器: "匹配器",
	"匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。": "符合這些主機的請求將直連，不經過 HTTP 代理；命令工具依同一份規則寫入 NO_PROXY。 多個規則以英文逗號分隔。",
	单次: "單次",
	"单次 (single)": "單次 (single)",
	"单次 · {0}": "單次 · {0}",
	单步调试: "單步調試",
	"单步运行中…": "單步運行中…",
	卸载: "卸載",
	"卸载插件及目录？": "卸載插件及目錄？",
	历史: "歷史",
	"压缩保留最近 Step 数": "壓縮保留最近 Step 數",
	压缩后: "壓縮後",
	压缩未完成: "壓縮未完成",
	原上下文已保留: "原始上下文已保留",
	"原上下文已保留 · {0}": "原始上下文已保留 · {0}",
	原始配置: "原始配置",
	"原文已变化或暂未加载，无法准确定位。": "原文已變化或暫未加載，無法準確定位。",
	"原模型「{0}」已不可用，已改用「{1}」": "原始模型「{0}」已不可用，已改用「{1}」",
	去登录: "去登入",
	参数: "參數",
	双击打开: "雙擊打開",
	双击文本预览: "雙擊文字預覽",
	"发现新版本 v": "發現新版本 v",
	"发现新版本 v{0}": "發現新版本 v{0}",
	"发现新版本 v{0}，点击下载": "發現新版本 v{0}，點選下載",
	"发现新版本 v{0}，点击打开下载页": "發現新版本 v{0}，點選開啟下載頁",
	发现新版本时会在顶部显示提示条: "發現新版本時會在上方顯示提示條",
	发送: "傳送",
	取消: "取消",
	取消下载: "取消下載",
	取消任务: "取消任務",
	取消固定右侧栏: "取消固定右側欄",
	取消固定左侧栏: "取消固定左側欄",
	"取消失败：{0}": "取消失敗：{0}",
	取消收藏: "取消收藏",
	"取消收藏：{0}": "取消收藏：{0}",
	"取消暴露为 Agent 工具": "取消暴露為 Agent 工具",
	取消更新: "取消更新",
	取消置顶: "取消置頂",
	"取消运行 {0}": "取消執行 {0}",
	"取消选择 {0}": "取消選擇 {0}",
	"只属于「{0}」的记忆 — 模型在会话里读它，你在这里整理它。": "只屬於「{0}」的記憶 — 模型在會話裡讀它，你在這裡整理它。",
	"只改变背景板，聊天区、输入栏和控件保持中性。": "只改變背景板，聊天區、輸入列和控制項保持中性。",
	可用模式: "可用模式",
	可用至: "可至",
	"可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。": "可選。填寫 PEM 根憑證路徑後，模型請求以它為信任根，並以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等變數注入 MCP 與命令工具；留空則使用系統信任鏈。",
	"可选：自然语言格式说明": "可選：自然語言格式說明",
	右侧工具: "右側工具",
	右侧工具栏: "右側工具列",
	合并: "合併",
	"合并多个输入，取首个有效值。": "合併多個輸入,取首個有效值。",
	"同一主题在两种模式下保持不同的明暗气质。": "同一主題在兩種模式下保持不同的明暗氣質。",
	同步项目: "同步項目",
	名称: "名稱",
	名称不能包含路径分隔符: "名稱不能包含路徑分隔符",
	"后端进程已停止响应（可能已崩溃）。请重启应用以恢复。": "後端進程已停止回應（可能已崩潰）。請重啟應用以恢復。",
	"向 Sub Agent 发送消息...": "向 Sub Agent 發送訊息...",
	"向 {0} 发送了消息": "向 {0} 發送了訊息",
	"向 {0} 发送消息失败": "向 {0} 發送訊息失敗",
	向下调整高度: "向下調整高度",
	"向供应商 API 发送的模型标识。": "傳送給供應商 API 的模型標識。",
	向右调整宽度: "向右調整寬度",
	启动时自动检查更新: "啟動時自動檢查更新",
	启用: "啟用",
	"启用 generate_image 工具": "啟用 generate_image 工具",
	启用了: "啟用了",
	"启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。": "啟用後 generate_image 工具才會上傳工具集；未啟用時呼叫會被攔截。",
	启用或关闭生图工具: "啟用或關閉生圖工具",
	"启用技能 {0}": "啟用技能 {0}",
	启用推理预算: "啟用推理預算",
	"启用插件 {0}": "啟用外掛程式 {0}",
	命中: "命中",
	命令: "命令",
	"命令 ": "指令",
	"命令 {0}": "指令 {0}",
	"命令…（curl/git/ffmpeg 等）": "指令…（curl/git/ffmpeg 等）",
	命令行: "命令列",
	命令输出: "命令輸出",
	回到子代理最新: "回到子代理最新",
	回到最新: "回到最新",
	回到最新消息: "回到最新消息",
	回到编辑: "回到編輯",
	回滚: "回滾",
	"固定 revision": "固定 revision",
	固定右侧栏: "固定右側欄",
	固定左侧栏: "固定左側欄",
	图标: "圖標",
	图标色彩: "圖示色彩",
	图片: "圖片",
	"图片加载失败：{0}": "圖片載入失敗：{0}",
	"图片暂时取不到，重试": "圖片暫時取不到，重試",
	图谱: "圖譜",
	"在 LamTools 手机端输入此数字": "在 LamTools 手機端輸入此數字",
	"在会话里让助手写下记忆，它就会出现在这里。": "在會話裡請助手寫下記憶，它就會出現在這裡。",
	"在当前能力范围内自动批准（工作目录外仍会确认）": "在目前能力範圍內自動核准(工作目錄外仍會確認)",
	在线: "在線",
	"在聊天里说出你的想法，助手会一边问一边把方案写进「": "在聊天裡說出你的想法，助手會一邊問一邊把方案寫進“",
	在里面新建文件夹: "在裡面新建資料夾",
	在里面新建记忆: "在裡面新記憶",
	处理中: "處理中",
	"处理中…": "處理中…",
	处理器类型: "處理器類型",
	处理您的日常任务: "處理您的日常任務",
	处理方式: "處理方式",
	备注: "備註",
	复位: "復位",
	复制: "複製",
	复制代码: "複製程式碼",
	复制回复: "複製回复",
	复制失败: "複製失敗",
	"复制失败：当前环境无法访问剪贴板": "複製失敗：目前環境無法存取剪貼簿",
	"复制完整 ID": "複製完整 ID",
	"复制完整会话 ID": "複製完整會話 ID",
	复制数字码: "複製數位碼",
	复制消息: "複製訊息",
	复制路径: "複製路徑",
	外观: "外觀",
	外观模式: "外觀模式",
	"外部搜索内核（subprocess / http）": "外部搜尋核心（subprocess / http）",
	多模态: "多模態",
	"多模态（支持图片）": "多模態（支援圖）",
	大纲: "大綱",
	失败: "失敗",
	"如 AGENTS.md / CONTEXT.md": "如 AGENTS.md / CONTEXT.md",
	"如 gpt-image-1 / flux 等，留空使用服务端默认": "如 gpt-image-1 / flux 等，留空使用服務端默認",
	"如 my-skill（字母/数字/._-）": "如 my-skill（字母/數字/._-）",
	"如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展": "如需存取獨立搜尋工具（如 baidu-serp-api、SearXNG、openserp 等），在原始設定中擴展",
	"如：我的 DeepSeek": "如：我的 DeepSeek",
	委派子代理: "委派子代理",
	"委派子代理：{0}": "委派子代理人：{0}",
	子代理: "子代理",
	"子代理 (agent)": "子代理程式 (agent)",
	"子代理 {0}": "子代理 {0}",
	子代理委派策略: "子代理委派策略",
	子代理资源统计: "子代理資源統計",
	子代理运行中: "子代理程式運行中",
	"子代理运行中：{0}": "子代理程式運行中：{0}",
	子层: "子層",
	子工作流: "子工作流程",
	子文档: "子文檔",
	"字段，例如：": "字段，例如：",
	字节读取完成: "位元組讀取完成",
	学习: "學習",
	"学习、探索、温习": "學習、探索、溫習",
	学科: "學科",
	"安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。": "安全閘道已啟動；LAN 使用 Noise 加密，公網連線透過自架 Relay。",
	安全边界: "安全邊界",
	安装: "安裝",
	"安装中…": "安裝中…",
	安装依赖: "安裝依賴",
	安装包约: "安裝包約",
	"安装完成后 Sunday 会自动重新打开。": "安裝完成後 Sunday 會自動重新開啟。",
	安装成功: "安裝成功",
	"安装成功：{0}": "安裝成功：{0}",
	安装插件: "安裝插件",
	"完全编辑、自动批准，并允许访问工作目录外": "完全編輯、自動批准，並允許存取工作目錄外",
	完全访问: "完整存取",
	完全访问已包含: "完全存取已包含",
	"完全访问模式会临时允许访问工作目录之外的路径。": "完全存取模式會暫時允許存取工作目錄以外的路徑。",
	完成: "完成",
	完整归档: "完整歸檔",
	"完整归档导出失败：{0}": "完整歸檔匯出失敗：{0}",
	"完整归档已保存：{0}": "完整歸檔已儲存：{0}",
	"完整归档正在准备中，请稍候。": "完整歸檔正在準備中，請稍候。",
	"官方发现与 Relay 必须登录": "官方發現與 Relay 必須登入",
	官方模板: "官方模板",
	定时任务: "排程任務",
	"定时任务 › {0}": "定時任務 › {0}",
	"定时任务 › 新建任务": "定時任務 › 新任務",
	"定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。 点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。": "定時任務是一條交給 Agent 的長期指令：到點它會自己開工，跑完把結果留在會話裡。 點右上角「創建定時任務」，或直接在聊天裡說「每天九點把 XX 做一遍」。",
	定时任务模板: "定時任務模板",
	定时切换: "定時切換",
	实时: "實時",
	实时预览: "即時預覽",
	实测: "實測",
	审批: "審批",
	容器内没有可选元素: "容器內沒有可選元素",
	宽松: "寬鬆",
	密码: "密碼",
	对话: "對話",
	导入: "匯入",
	"导入 JSON": "導入 JSON",
	"导入失败：{0}": "導入失敗：{0}",
	导入工作流: "導入工作流程",
	导出: "匯出",
	"导出失败（{0}）": "匯出失敗（{0}）",
	"导出失败：{0}": "匯出失敗：{0}",
	将移除此处的: "將移除此處的",
	"将丢弃：{items}。已完成的工具结果会保留，终止后不能继续。": "將丟棄：{items}。已完成的工具結果會保留，終止後不能繼續。",
	"尚未启动 Sub Agent": "尚未啟動 Sub Agent",
	"尚未生成配对码。": "尚未產生配對碼。",
	尚未登录服务器账号: "尚未登入伺服器帳號",
	尚未评估: "尚未評估",
	尚未连接: "尚未連接",
	"尚未配对手机。": "尚未配對手機。",
	尝试: "嘗試",
	就绪: "就緒",
	局域网: "區域網路",
	"局部图超过建议范围（{0} 节点 / {1} 条关系），已保持分页；当前布局在主线程分层计算。": "局部圖超過建議範圍（{0} 節點 / {1} 條關係），已保持分頁；目前佈局在主執行緒分層計算。",
	展开: "展開",
	搜索图层: "搜尋圖層",
	没有匹配的图层: "沒有符合的圖層",
	吸附: "吸附",
	辅助线: "輔助線",
	父级: "父級",
	尺寸: "尺寸",
	宽度: "寬度",
	高度: "高度",
	填充: "填滿",
	内容适配: "內容適配",
	固定值: "固定值",
	未设置: "未設定",
	最小: "最小",
	最大: "最大",
	背景透明度: "背景透明度",
	图片格式无法识别: "圖片格式無法識別",
	"SVG 不允许包含脚本": "SVG 不允許包含腳本",
	"展开 ": "展開",
	"展开 {0}": "展開 {0}",
	"展开{0}分区": "展開{0}分割區",
	展开全部会话: "展開全部會話",
	"展开另外 {0} 个会话": "展開另外 {0} 個會話",
	展开最近会话: "展開最近會話",
	展开运行详情: "展開運作詳情",
	工作业务: "工作業務",
	工作区: "工作區",
	"工作区域保持纯色，颜色只用于控件层级。": "工作區域保持純色，顏色只用於控制層級。",
	工作台: "工作台",
	"工作根目录：": "工作根目錄：",
	工作模式列表: "工作模式列表",
	工作模式详情: "工作模式詳情",
	工作流: "工作流程",
	工作流不存在: "工作流程不存在",
	工作流名称: "工作流程名稱",
	工作流对话: "工作流程對話",
	工作流有未保存修改: "工作流程有未儲存修改",
	工作流检查器: "工作流程檢查器",
	工作流画布: "工作流程畫布",
	工作流画布操作: "工作流程畫布操作",
	工作流缩略图: "工作流程縮圖",
	工作流节点操作: "工作流程節點操作",
	工作流节点目录: "工作流程節點目錄",
	工作流触发器与激活: "工作流程觸發器與激活",
	工作流资源: "工作流程資源",
	工作流运行输入: "工作流程運作輸入",
	工作流连线操作: "工作流程連線操作",
	工作流队列与历史: "工作流程佇列與歷史",
	工作环境: "工作環境",
	"工作环境：{0}": "工作環境：{0}",
	工作目录: "工作目錄",
	"工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。": "工作目錄外的讀寫與命令列存取會先徵求你的確認，批准後本次執行。",
	工作目录外访问: "工作目錄外訪問",
	"工作目录外访问设置保存失败，已回滚：{0}": "工作目錄外存取設定儲存失敗，已回溯：{0}",
	工作目录外需确认: "工作目錄外需確認",
	工具: "工具",
	"工具 {0} 不可用：请求了当前环境没有注册的工具。": "工具 {0} 不可用：請求了目前環境沒有註冊的工具。",
	工具不可用: "工具不可用",
	"工具不可用：{0}": "工具不可用：{0}",
	工具列表: "工具列表",
	工具执行前请求批准: "工具執行前請求批准",
	工具模式: "工具模式",
	工具调用: "工具調用",
	工具集: "工具集",
	左对齐: "左對齊",
	已中断: "已中斷",
	"已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。": "已從此處建立分叉會話；僅複製對話歷史，未複製工作區或運行時狀態。",
	已保存: "已儲存",
	"已保存，重启后端后生效。": "已儲存，重新啟動後端後生效。",
	"已保存：{0}": "已儲存：{0}",
	"已保留本地修改，正在重试保存…": "已保留本地修改，正在重試保存…",
	已信任: "已信任",
	已修改: "已修改",
	已停用: "已停用",
	"已停用。": "已停用。",
	已停用触发器: "已停用觸發器",
	已允许: "已允許",
	已关闭: "已關閉",
	已创建任务: "已建立任務",
	"已创建：{0}": "已建立：{0}",
	"已删除此轮及之后的对话；文件与成果保持不变。": "已刪除此輪及之後的對話；文件與成果保持不變。",
	"已加入队列：{0}": "已加入佇列：{0}",
	已压缩: "已壓縮",
	"已发布 v": "已發布 v",
	已取消: "已取消",
	"已取消完整归档导出。": "已取消完整歸檔匯出。",
	已取消暴露: "已取消暴露",
	已取消队列运行: "已取消佇列運行",
	已启用: "已啟用",
	已复制: "已複製",
	"已复制 {0} 个元素": "已複製 {0} 個元素",
	"已复制完整会话 ID": "已複製完整會話 ID",
	已失联: "已失聯",
	已完成: "已完成",
	"已完成|已失败|已中断|已取消": "已完成|已失敗|已中斷|已取消",
	"已导入：{0}": "已導入：{0}",
	"已导出工作流 JSON": "已匯出工作流程 JSON",
	"已导出：{0}": "已匯出：{0}",
	已就绪: "已就緒",
	"已就绪 · 已配置密钥": "已就緒 · 已設定金鑰",
	已开启: "已開啟",
	已截断: "已截斷",
	已打开: "已開啟",
	已收藏: "已收藏",
	"已新增触发器，请填写配置后保存。": "已新增觸發器，請填寫配置後儲存。",
	"已是最新版本（v": "已是最新版本（v",
	"内部测试版，已跳过应用内更新检查（请用 update-constant.ps1 更新）": "內部測試版，已跳過應用程式內更新檢查（請用 update-constant.ps1 更新）",
	已暂停: "已暫停",
	"已暂停（单步）": "已暫停（單步）",
	已暴露: "已曝光",
	"已暴露：{0}": "已曝光：{0}",
	"已替换并激活。": "已替換並啟動。",
	已替换并激活触发器: "已取代並啟動觸發器",
	已标记: "已標記",
	"已添加 {0} 个目录": "已新增 {0} 個目錄",
	"已添加节点：{0}": "已新增節點：{0}",
	"已清理 {0} 个队列/历史项": "已清理 {0} 個佇列/歷史項",
	"已激活。": "已啟動。",
	已激活触发器: "已啟動觸發器",
	已登录: "已登入",
	已禁用: "已停用",
	已移除: "已移除",
	"已粘贴 {0} 个元素": "已貼上 {0} 個元素",
	已获取: "已獲取",
	已设为默认模型: "已設為預設模型",
	已评估但未通过: "已評估但未通過",
	"已读取：{0}": "已讀取：{0}",
	"已调用{0}个工具…": "已呼叫{0}個工具…",
	已跳过: "已跳過",
	已运行: "已運行",
	已连接: "已連接",
	已退出: "已退出",
	已选: "已選",
	已选中容器: "已選取容器",
	"已通过，掌握{0}": "已通過，掌握{0}",
	已配对移动设备: "已配對行動設備",
	已配对设备: "已配對設備",
	"已配置（留空保持原密钥）": "已設定（留空保持原金鑰）",
	已采用远端版本: "已採用遠端版本",
	"已重命名：{0}": "已重新命名：{0}",
	已锁定区域: "已鎖定區域",
	布局: "佈局",
	带输入运行: "附輸入運行",
	常量: "常數",
	常量值: "常數值",
	"并发 {0}": "並發 {0}",
	并发上限: "併發上限",
	库根: "庫根",
	应用: "應用",
	建议: "建議",
	建议模型: "建議模型",
	"建议模型 {0}": "建議模型 {0}",
	开启: "開啟",
	"开启后生成设备身份和一次性六位数字配对码。": "開啟後產生裝置身分與一次六位數配對碼。",
	开启手机控制: "開啟手機控制",
	开启网格吸附: "開啟網格吸附",
	开始: "開始",
	开始使用: "開始使用",
	"开始前需要配置一个模型供应商，让 Agent 能思考与回复。": "開始前需要設定一個模型供應商，讓 Agent 思考回應。",
	"开始时间（可选）": "開始時間（可選）",
	开始配置: "開始配置",
	开工: "開工",
	引导: "引導",
	引擎: "引擎",
	引用: "引用",
	"引用外部工作流，iterate 控制执行模式": "引用外部工作流程，iterate 控制執行模式",
	归到文件夹: "歸到資料夾",
	归属此账号的设备: "歸屬此帳號的設備",
	"当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明": "當主模型為文字模型且需要理解圖片/影片等附件時，能力提示字會引導主 Agent 用此模型委派 sub_agent 檢視。僅顯示已聲明",
	当前主题: "當前主題",
	当前会话: "目前會話",
	当前会话可临时切换: "目前會話可暫時切換",
	当前会话说明: "目前會話說明",
	"当前使用内置默认：{0}": "目前使用內建預設：{0}",
	当前供应商: "目前供應商",
	"当前全局基线：{0}": "目前全域基線：{0}",
	当前六位数字配对码: "目前六位數配對碼",
	当前六位配对码: "目前六位配對碼",
	"当前内核：{0}": "目前核心：{0}",
	当前显示: "目前顯示",
	"当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。": "目前未設定 Relay，手機無法僅以數位碼發現這台電腦；請先設定遠端中轉服務。",
	"当前来源：全局配置": "目前來源：全域配置",
	"当前来源：内置默认（未配置全局 guide）": "目前來源：內建預設（未配置全域 guide）",
	"当前来源：继承全局 / 内置默认（未配置项目级 guide）": "目前來源：繼承全域 / 內建預設（未配置專案級 guide）",
	"当前来源：项目配置": "目前來源：專案配置",
	当前桌面工作环境: "目前桌面工作環境",
	当前模型组: "目前模型組",
	当前模式: "目前模式",
	当前模式由插件提供: "目前模式由外掛程式提供",
	"当前步骤：第 {0} 步，{1}，{2}": "目前步驟：第 {0} 步，{1}，{2}",
	"当前没有 checklist": "目前沒有 checklist",
	当前没有可分叉的会话: "目前沒有可分叉的會話",
	当前没有可回退的会话: "目前沒有可回退的會話",
	"当前没有可用的项目，无法打开文件": "目前沒有可用的項目，無法開啟文件",
	当前没有可编辑的会话: "目前沒有可編輯的會話",
	当前没有排队运行: "目前沒有排隊運行",
	"当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 {0} 条。": "目前沒有項目覆蓋，沿用全域基線；同名任務類型新增項目規則後將由項目覆寫。當前生效 {0} 條。",
	当前版本: "目前版本",
	"当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。": "目前版本與軟體更新（優先讀取官網更新清單，官網不可達時回退 GitHub Releases）。",
	"当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）": "目前環境不支援拖曳安裝（請使用 Release URL 貼上安裝）",
	当前环境不支持文件导出: "目前環境不支援文件匯出",
	当前环境不支持文件选择: "目前環境不支援文件選擇",
	当前环境不支持附件选择: "目前環境不支援附件選擇",
	"当前笔记没有保存处理，修改仍保留。": "目前筆記沒有儲存處理，修改仍保留。",
	当前组: "目前組",
	"当前继承全局有效策略：{0}": "目前繼承全域有效策略：{0}",
	当前计划: "当前计划",
	当前账号: "当前账号",
	"当前选择：{0}": "目前選擇：{0}",
	当前配对码: "当前配对码",
	当前队列: "目前隊列",
	当前项目: "目前項目",
	"当前项目没有本地覆盖。": "目前項目沒有本地覆蓋。",
	"当前项目覆盖：{0}": "目前項目覆蓋：{0}",
	"当前项目还没有可用会话。新建会话后即可开始工作。": "目前項目還沒有可用會話。新建會話後即可開始工作。",
	当前默认状态: "目前預設狀態",
	待你选择: "待你选择",
	待处理: "待處理",
	待处理项: "待处理项",
	待定: "待定",
	待审核: "待审核",
	待接入: "待接入",
	待评定: "待评定",
	待配置: "待配置",
	"待配置 · 缺少 API Key": "待設定 · 缺少 API Key",
	循环: "循環",
	"循环 (loop)": "循环 (loop)",
	必填: "必填",
	"必须与所选供应商的 API 基础 URL 一致。": "必須與所選供應商的 API 基礎 URL 一致。",
	快捷操作: "快速操作",
	快速开始: "快速開始",
	思索: "思索",
	思考: "思考",
	"思考中…": "思考中…",
	"思考了{0}s": "思考了{0}s",
	思考了一会: "思考了一會",
	思考模式: "思考模式",
	思考等级: "思考等级",
	思考等级选项: "思考等級選項",
	恢复: "恢復",
	"恢复 {0}": "還原 {0}",
	恢复到成果库: "恢復到成果庫",
	恢复默认: "恢復默認",
	"想了解什么？": "想了解什麼？",
	"想如何整理笔记…": "想如何整理筆記…",
	"想学什么…": "想學什麼…",
	成员: "成員",
	成果: "成果",
	成果列表: "成果列表",
	成果库: "成果庫",
	成果筛选: "成果篩選",
	"我想学{0}，给我讲一下": "我想學{0}，跟我講一下",
	"或粘贴 GitHub Release URL：": "或貼上 GitHub Release URL：",
	截止: "截止",
	"所选目录在工作区之外，已保留绝对路径": "所選目錄在工作區之外，已保留絕對路徑",
	手动: "手動",
	手动触发无需排程: "手動觸發無需排程",
	手动运行: "手動運行",
	"手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。 自动送达（账号直传）尚未接入，先用导出／导入这一步。": "手機做方案，電腦開工：方案先存在手機上，桌面端導入後即可核對並開始執行。 自動送達（帳號直傳）尚未接入，先用匯出／匯入這一步驟。",
	手机控制: "手機",
	"手机控制命令将在桌面 Tauri 运行时启用": "手機控制指令將在桌面 Tauri 運行時啟用",
	"手机控制命令将在桌面 Tauri 运行时启用。": "手機控制指令將在桌面 Tauri 運行時啟用。",
	手机控制未能启动: "手機控制未能啟動",
	"手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。": "手機提交數位碼後，Relay 只解析連線元資料；真正的配對認證和會話資料仍透過 Noise 加密隧道完成。",
	"手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。": "手機端還沒有接上記憶目錄：在會話裡請助手用記憶工具整理，或連上桌面端在這裡瀏覽。",
	手机配对: "手機配對",
	打开: "打開",
	"打开 ": "打開",
	"打开 {0}": "開啟 {0}",
	"打开 {0} 的项目记忆": "開啟 {0} 的項目記憶",
	"打开「{0}」失败：{1}": "開啟「{0}」失敗：{1}",
	"打开会话 {0}": "開啟會話 {0}",
	打开右侧面板: "打開右側面板",
	"打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。": "開啟後阻止系統進入空閒休眠（手動睡眠、合蓋休眠不受影響），長任務不會中斷。",
	"打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。": "開啟後，模型的提問卡超過 5 分鐘無人回答，會依照「使用者跳過」回傳，本輪繼續往下走。 需要你授權的審核卡不受影響，會一直等你處理。",
	"打开完整设置（账号与设备）": "打开完整设置（账号与设备）",
	打开工作区: "開啟工作區",
	打开左侧会话栏: "打开左侧会话栏",
	"打开快捷操作，当前模式 {0}": "開啟快速操作，目前模式 {0}",
	打开文件夹: "開啟資料夾",
	"打开文件夹 {0}": "開啟資料夾 {0}",
	打开的工作流: "打开的工作流",
	"打开笔记 {0}": "開啟筆記 {0}",
	打开视窗: "打開視窗",
	打开账号与设备: "打开账号与设备",
	打开附件失败: "打开附件失败",
	"打开附件选择器失败：{0}": "開啟附件選擇器失敗：{0}",
	"打开项目 {0}": "開啟項目 {0}",
	执行: "執行",
	"执行 Python 脚本，并通过端口传递变量。": "執行 Python 腳本,並透過連接埠傳遞變數。",
	执行中: "執行中",
	执行前显示给用户的状态文字: "执行前显示给用户的状态文字",
	"执行动作？": "執行動作？",
	执行步骤: "執行步驟",
	"执行进度：{0}": "執行進度：{0}",
	扩展: "擴充",
	扩展提示: "擴充提示",
	"扩展自身的审批等级与 hard block 由各自的管理入口负责。": "擴展自身的審核等級與 hard block 由各自的管理入口負責。",
	"扫描中…": "掃描中…",
	扫描目录: "掃描目錄",
	批准: "批准",
	技能: "技能",
	"技能加载后 Agent 应遵循的完整指引……": "技能載入後 Agent 應遵循的完整指引…",
	把这份方案交给当前会话执行: "把这份方案交给当前会话执行",
	折叠: "折疊",
	"折叠 {0}": "折疊 {0}",
	"折叠{0}分区": "折疊{0}分區",
	折叠最近会话: "折叠最近会话",
	拍摄一张新照片: "拍一張新照片",
	拒绝: "拒絕",
	"拖动 {0} 模块排序": "拖曳 {0} 模組排序",
	拖动排序: "拖曳排序",
	拖动调整宽度: "拖曳調整寬度",
	拖动调整宽高: "拖曳調整寬高",
	拖动调整高度: "拖动调整高度",
	"拖拽 .zip 文件到此处安装": "拖拽 .zip 文件到此处安装",
	拖拽到这里上传: "拖曳到這裡上傳",
	指令: "指令",
	"指令…": "指令…",
	指标: "指標",
	按供应商: "按供應商",
	按供应商分类的模型: "按供应商分类的模型",
	"按修改时间（新到旧）": "按修改时间（新到旧）",
	按名称: "按名稱",
	"按工作流 input_params 传入": "依工作流程 input_params 傳入",
	"按条件选择后续分支。": "依條件選擇後續分支。",
	按清单使用工具: "依清單使用工具",
	按状态筛选: "依狀態篩選",
	按类型筛选: "依類型篩選",
	按组: "按組",
	按组分类的模型: "按組別分類的模型",
	"按组新增模型时必须填写 API 基础 URL": "依群組新增模型時必須填寫 API 基礎 URL",
	按角色筛选: "依角色篩選",
	"按计划运行任务，或在需要时随时执行。": "按計畫執行任務，或在需要時隨時執行。",
	"换个关键词再试。": "換個關鍵字再試。",
	换个关键词试试: "换个关键词试试",
	排队: "排隊",
	消息发送: "訊息傳送",
	直接引导: "直接引導",
	"Enter 发送方式": "Enter 傳送方式",
	"打开时直接按 Enter 会把消息立即交给当前回合；关闭时直接按 Enter 先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种。会话空闲时两个键都开新回合，两个键都不会改动已排队的项。": "開啟時直接按 Enter 會把訊息立即交給目前回合；關閉時直接按 Enter 先進入輸入佇列，本輪結束後按順序送出。Ctrl+Enter 永遠執行另一種。工作階段閒置時兩個鍵都開新回合，兩個鍵都不會改動已排隊的項目。",
	"Enter 直接引导": "Enter 直接引導",
	"当前：Enter 直接引导，Ctrl+Enter 排队": "目前：Enter 直接引導，Ctrl+Enter 排隊",
	"当前：Enter 排队，Ctrl+Enter 直接引导": "目前：Enter 排隊，Ctrl+Enter 直接引導",
	"会话正在运行时发送消息的去向：直接引导会把消息立即交给当前回合；排队会先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种，且两个键都不会改动已排队的项。": "工作階段執行中時訊息的去向：直接引導會立即交給目前回合；排隊會先進入輸入佇列，本輪結束後按順序送出。Ctrl+Enter 永遠執行另一種，且兩個鍵都不會改動已排隊的項目。",
	"排队项，可拖拽调整顺序": "排隊項目，可拖曳調整順序",
	拖拽调整顺序: "拖曳調整順序",
	"排队失败：{0}": "排隊失敗：{0}",
	"排除的默认上下文文件（except）": "排除的預設上下文檔案（except）",
	接口类型: "介面類型",
	接口类型与适配参数: "介面類型與適配參數",
	"接收 {0} 消息失败": "接收 {0} 訊息失敗",
	"接收工作流输入。": "接收工作流程輸入。",
	控件: "控件",
	控制: "控制",
	"控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。": "控製檔案操作的預設範圍；較高風險的規則仍由 Sunday 強制執行。",
	"控制新会话的默认权限；当前任务可以在输入框中临时调整。": "控制新會話的預設權限；目前任務可以在輸入框中暫時調整。",
	"控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。": "控制模型能看到哪些工具，以及工具在思索 / 執行模式下的暴露方式。",
	"控制过程行前的常规、运行与完成图标；等待和错误仍使用状态色。": "控制流程行前的常規、運行與完成圖示；等待與錯誤仍使用狀態色。",
	推理: "推理",
	推理预算: "推理預算",
	"描述（description）": "描述（description）",
	提交: "提交",
	"提交中…": "提交中…",
	"提交数据必须是 JSON 对象": "提交資料必須是 JSON 對象",
	"提交数据必须是有效 JSON": "提交資料必須是有效 JSON",
	"提交数据（JSON）": "提交資料（JSON）",
	提示文本: "提示文本",
	提示文本不能为空: "提示文字不能為空",
	提问: "提問",
	提问自动继续: "提問自動繼續",
	插件: "外掛程式",
	"插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件可禁用、不可卸载；每个插件按平台分类（通用 / 桌面端专用 / 移动端专用），本机只列出适用的部分。": "插件 = 工具 / 技能 / Hooks / MCP 的統一安裝單元。內建插件可停用、不可卸載；每個插件按平台分類（通用 / 桌面端專用 / 行動端專用），本機只列出適用的部分。",
	"插件与 MCP": "插件與 MCP",
	"插件与 MCP 的 hard block 不能从此页解除。": "外掛程式與 MCP 的 hard block 不能從此頁解除。",
	更多插件: "更多外掛程式",
	在分屏中打开: "在分屏中開啟",
	在右侧分屏中打开: "在右側分屏中開啟",
	在下方分屏中打开: "在下方分屏中開啟",
	插件分区: "外掛程式分區",
	插件功能不可用: "外掛功能不可用",
	插件未返回有效数据: "外掛程式未回傳有效數據",
	"插件目录或 .zip 路径": "插件目錄或 .zip 路徑",
	"插值）": "內插）",
	"插入 Callout": "插入 Callout",
	"插入 Mermaid 图": "插入 Mermaid 圖",
	插入代码块: "插入程式碼區塊",
	插入公式: "插入公式",
	插入引用: "插入引用",
	插入表格: "插入表格",
	搜索: "搜尋",
	"搜索 {0}": "搜尋 {0}",
	"搜索不可用：{0}": "搜尋不可用：{0}",
	"搜索中…": "搜尋中…",
	"搜索了{0}次": "搜尋了{0}次",
	"搜索了{0}次…": "搜尋了{0}次…",
	"搜索任务、插件或文件": "搜尋任務、外掛程式或文件",
	搜索供应商: "搜尋供應商",
	搜索内容: "搜尋內容",
	"搜索名称、分类或说明": "搜尋名稱、分類或說明",
	"搜索名称、路径或来源…": "搜尋名稱、路徑或來源…",
	搜索工作区索引: "搜尋工作區索引",
	搜索工具: "搜尋工具",
	搜索成果库: "搜尋成果庫",
	"搜索插件未启用。到「插件」页启用 websearch 后可用。": "搜尋插件未啟用。到「外掛」頁啟用 websearch 後可用。",
	搜索服务响应正常: "搜尋服務回應正常",
	搜索模型: "搜尋模型",
	搜索模型组: "搜尋模型組",
	搜索模式: "搜尋模式",
	搜索结果: "搜尋結果",
	搜索节点: "搜尋節點",
	搜索范围: "搜尋範圍",
	搜索记忆: "搜尋記憶",
	搜索资料库: "搜尋庫",
	搜索项目: "搜尋項目",
	搜索项目和会话: "搜尋項目和會話",
	撤回: "撤回",
	撤销: "撤銷",
	撤销后设备立即失去访问权限: "撤銷後設備立即失去存取權限",
	"撤销（Ctrl/Cmd+Z）": "撤銷（Ctrl/Cmd+Z）",
	操作: "操作",
	操作失败: "操作失敗",
	"操作失败：{0}": "操作失敗：{0}",
	支持推理: "支持推理",
	"支持注释（JSONC），保存后即时生效。": "支援註解（JSONC），儲存後即時生效。",
	"收到了 {0} 的消息": "收到了 {0} 的訊息",
	收藏: "收藏",
	"收藏：{0}": "收藏：{0}",
	收起: "收合",
	"收起 ": "收起",
	"收起 {0}": "收起 {0}",
	收起会话: "收起會話",
	收起计划: "收起計劃",
	收起运行详情: "收起運行詳情",
	放大: "放大",
	放大对话: "放大對話",
	放弃: "放棄",
	放弃修改: "放棄修改",
	"放弃未保存的修改？": "放棄未儲存的修改？",
	放弃本地修改并采用远端版本: "放棄本地修改並採用遠端版本",
	"敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。": "敏感路徑（如 .env、SSH 憑證）寫入和編輯仍會阻斷。",
	教学示意图: "教學示意圖",
	教学配图: "教學配圖",
	数据: "數據",
	整理: "整理",
	文件: "文件",
	"文件 {0}": "文件 {0}",
	"文件 · ": "文件 ·",
	文件名: "檔案名",
	"文件名（如 TEAM_RULES.md）": "檔案名稱（如 TEAM_RULES.md）",
	文件夹: "資料夾",
	文件夹名: "資料夾名",
	文件夹名称: "資料夾名稱",
	文件改动: "文件改動",
	"文件结束 · ": "文件結束 ·",
	文件缺失: "文件缺失",
	文件边界: "文件邊界",
	文本: "文本",
	文本操作: "文字操作",
	文本记录: "文字記錄",
	文本颜色: "文字顏色",
	"文本（不支持图片）": "文字（不支援圖片）",
	文档: "文檔",
	文档大纲: "文件大綱",
	文档知识: "文件知識",
	斜体: "斜體",
	新任务: "新任務",
	新会话将从这里开始: "新會談將從這裡開始",
	新会话默认: "新會話默認",
	"新供应商需要填写名称和 API Key": "新供應商需要填寫名稱和 API Key",
	新增: "新增",
	"新增 Hook": "新增 Hook",
	"新增 {0} 行": "新增 {0} 行",
	"新增一个模式后，就可以设置它能使用的工具。": "新增一個模式後，就可以設定它能使用的工具。",
	新增供应商: "新增供應商",
	新增模型: "新增模型",
	新增模式: "新增模式",
	新增第一条角色分配: "新增第一個角色分配",
	新增触发器: "新增觸發器",
	新建: "新建",
	新建任务: "新任務",
	新建会话: "新增對話",
	新建定时任务: "新建定時任務",
	新建工作流: "新建工作流程",
	新建技能: "新建技能",
	新建文件夹: "新建資料夾",
	"新建文件夹…": "新建資料夾…",
	新建方案: "新建方案",
	新建模型组: "新建模型組",
	新建节点: "新建節點",
	新建记忆: "新記憶",
	新建项目: "新增專案",
	方案: "方案",
	方案传输: "方案傳輸",
	方案名称: "方案名稱",
	"方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态": "方案就緒後才能開工 — 在聊天裡對助手說\"可以開工了\"，它會更新方案狀態",
	方案编辑: "方案編輯",
	方案阅读: "方案閱讀",
	无依赖: "無依賴",
	无多模态模型: "無多模態模型",
	无工具: "無工具",
	无序列表: "無序列表",
	无技能: "無技能",
	"无法创建模型组 {0}": "無法建立模型群組 {0}",
	"无法打开学习会话，请重试": "無法開啟學習會話，請重試",
	"无法打开：{0}": "無法開啟：{0}",
	无法显示: "無法顯示",
	"无法更新连线：端口类型不兼容或端口不存在": "無法更新連線：連接埠類型不相容或連接埠不存在",
	"无法读取文本：{0}": "無法讀取文字：{0}",
	"无法连接服务器：{0}": "無法連接伺服器：{0}",
	"无法连接：端口类型不兼容或端口不存在": "無法連線：連接埠類型不相容或連接埠不存在",
	无钩子: "無鉤子",
	无需压缩: "無需壓縮",
	日: "日",
	日出渐变: "日出漸變",
	日历: "日曆",
	日历触发器需要时间: "日曆觸發器需要時間",
	日历频率: "日曆頻率",
	日志: "日誌",
	日期: "日期",
	时区: "時區",
	时间: "時間",
	"时间 {0}": "時間 {0}",
	映射: "映射",
	"显式替换现有激活，并固定到当前 revision": "明確替換現有激活，並固定到當前 revision",
	显示名称: "顯示名稱",
	显示已移除: "顯示已移除",
	显示更早的过程: "顯示更早的過程",
	显示模块: "顯示模組",
	晨会摘要: "晨會摘要",
	晨宵: "晨宵",
	智能: "智能",
	智能体: "智慧代理",
	"智能体目标…": "智能體目標…",
	"暂不可用：{0}": "暫不可用：{0}",
	暂停: "暫停",
	"暂停工作流，等待人工批准或拒绝。": "暫停工作流程,等待手動批准或拒絕。",
	暂无: "暫無",
	暂无上下文: "尚無上下文",
	暂无上下文统计: "暫無上下文統計",
	暂无会话: "暫無會話",
	"暂无内容，创建一个开始。": "暫無內容，創造一個開始。",
	"暂无可显示的 Sub Agent 事件。": "暫無可顯示的 Sub Agent 事件。",
	暂无可添加的模型: "暫無可添加的模型",
	暂无可用工具: "暫無可用工具",
	暂无可用数据: "暫無可用數據",
	暂无可用模型: "暫無可用模型",
	"暂无可用模型，可手动输入模型 ID": "暫無可用模型，可手動輸入模型 ID",
	暂无已登记项目: "暫無已登記項目",
	"暂无已登记项目。": "暫無已登記項目。",
	"暂无已移除的成果。": "暫無已移除的成果。",
	暂无待处理任务: "暫無待處理任務",
	"暂无消息，发送一个任务。": "暫無訊息，發送一個任務。",
	"暂无笔记关系。": "暫無筆記關係。",
	"暂无符合筛选条件的成果。": "暫無符合篩選條件的成果。",
	暂无节点: "暫無節點",
	"暂无触发器。新增后可配置手动或定时入口。": "暫無觸發器。新增後可設定手動或定時入口。",
	"暂无资源统计。": "暫無資源統計。",
	"暴露为 Agent 工具": "暴露為 Agent 工具",
	更多: "更多",
	更新: "更新",
	"更新 v{0} 已下载并校验，点击安装": "更新 v{0} 已下載並校驗，點選安裝",
	更新于: "更新於",
	更新任务清单: "更新任務清單",
	更新定时任务失败: "更新定時任務失敗",
	"更新模型标识、能力和运行参数。": "更新模型標識、能力和運行參數。",
	更新计划: "更新計劃",
	"更新连接信息，已有密钥不会被覆盖。": "更新連線訊息，已有金鑰不會被覆蓋。",
	替换并激活: "替換並啟動",
	最低思考强度: "最低思考強度",
	"最低思考强度 {0}": "最低思考強度 {0}",
	最后一个: "最後一個",
	最多运行次数: "最多運行次數",
	最大化: "最大化",
	最大并发: "最大併發",
	最大输出: "最大輸出",
	最大运行次数: "最大運行次數",
	"最大运行次数（可选）": "最大運行次數（可選）",
	最大迭代: "最大迭代",
	最小化: "最小化",
	"最小间隔（秒）": "最小間隔（秒）",
	最新版本: "最新版本",
	最近: "最近",
	"最近一次 {0}": "最近一次 {0}",
	最近任务: "最近任务",
	最近打开: "最近打開",
	最近项目: "近期項目",
	最高思考强度: "最高思考強度",
	"最高思考强度 {0}": "最高思考強度 {0}",
	有序列表: "有序列表",
	有效期至: "有效期限至",
	有新版本可用: "有新版本可用",
	有未保存修改: "有未儲存修改",
	有未保存的修改: "有未儲存的修改",
	服务器: "伺服器",
	"服务器地址必须使用 HTTP 或 HTTPS": "伺服器位址必須使用 HTTP 或 HTTPS",
	服务器地址格式无效: "伺服器位址格式無效",
	"服务器未返回有效的桌面 Node": "伺服器未傳回有效的桌面 Node",
	"服务器请求失败（{0}）": "伺服器請求失敗（{0}）",
	服务器账号: "伺服器帳號",
	服务器返回了无效的登录凭据: "伺服器傳回了無效的登入憑證",
	服务地址: "服務地址",
	未上报: "未上報",
	未上报缓存: "未上報緩存",
	未保存: "未保存",
	未关联供应商: "未關聯供應商",
	未分组: "未分組",
	"未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。": "未發現任何 Hook。點選「新增 Hook」建立事件鉤子，或切換到「原始設定」手寫 JSON。",
	"未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为": "未發現任何 Skill。點選「新技能」創建，或將 SKILL.md 放入技能目錄（桌面端為",
	未发现新目录: "未發現新目錄",
	未启用: "未啟用",
	未命中: "未命中",
	未命名定时任务: "未命名定時任務",
	未命名工作流: "未命名工作流程",
	未命名来源: "未命名來源",
	未命名节点: "未命名節點",
	未命名运行: "未命名運行",
	未命名项目: "未命名項目",
	"未安装 RAG 插件；可尝试兼容搜索": "未安装 RAG 插件；可尝试兼容搜索",
	未找到匹配的项目或会话: "未找到符合的項目或會話",
	"未找到对应笔记，无法导航。": "找不到對應筆記，無法導航。",
	"未找到该消息（可能已被删除或属于子会话）": "未找到该消息（可能已被删除或属于子会话）",
	"未找到：{0}": "未找到：{0}",
	未指定: "未指定",
	未提供命令: "未提供指令",
	"未提取到正文摘要。": "未擷取至正文摘要。",
	未检查: "未檢查",
	未激活: "未激活",
	未登录: "未登入",
	未知: "未知",
	未知命令: "未知命令",
	未知触发方式: "未知觸發方式",
	未获取: "未獲取",
	"未获得收益 · ": "未獲得收益 ·",
	"未记录任务内容。": "未記錄任務內容。",
	未设置事件: "未設定事件",
	未设置时间: "未設定時間",
	"未设置（可在设置中调整）": "未設定（可在設定中調整）",
	未运行: "未運行",
	未连接到搜索服务: "未連線至搜尋服務",
	未选择: "未選擇",
	未配置: "未配置",
	"未配置（使用内置兜底：{0}）": "未配置（使用內建兜底：{0}）",
	"未回答的子代理提问 {count} 个": "未回答的子代理提問 {count} 個",
	未完成的步骤: "未完成的步驟",
	"本地 zip 路径": "本機 zip 路徑",
	本地目录: "本地目錄",
	本机: "本機",
	"本机命令工具使用的 shell": "本機指令工具使用的 shell",
	本机身份: "本機身份",
	本轮产出: "本輪產出",
	"机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。": "機器記憶體不足導致本輪中斷時，Sunday 會說明原因，並寫明「可用記憶體大於多少就自動繼續」； 記憶體回來後在同一會話自動開新一輪接著做，最多連續 3 次。你自己先發了新訊息時不再自動繼續。",
	权限: "權限",
	"权限偏好保存失败：{0}": "權限偏好儲存失敗：{0}",
	权限审批: "權限審批",
	"权限审批与输入框保持一致；工具清单由“工具模式”管理。": "權限核准與輸入框保持一致；工具清單由「工具模式」管理。",
	权限审批选项: "權限審批選項",
	"权限模式保存失败，已回滚：{0}": "權限模式儲存失敗，已回溯：{0}",
	条件: "條件",
	条关系: "條關係",
	条用户指令: "條使用者指令",
	来源: "來源",
	来自子代理: "來自子代理",
	松开以安装: "鬆開以安裝",
	松开鼠标上传附件: "放開滑鼠上傳附件",
	极光渐变: "極光漸變",
	极高: "極高",
	构建稳定的工作流程: "建構穩定的工作流程",
	查看: "查看",
	"查看 git 差异": "看 git 差異",
	"查看 git 状态": "查看 git 狀態",
	查看全文: "看全文",
	"查看其余 ": "看其餘",
	"查看其余 {0} 步": "看其餘 {0} 步",
	查看发布说明: "查看發布說明",
	查看官方文档: "查看官方文檔",
	标准: "標準",
	标准输出: "標準輸出",
	标记: "標記",
	标题: "標題",
	"标题（name）": "標題（name）",
	框架: "框架",
	"框架.{0}": "框架.{0}",
	桌面端专用: "桌面端專用",
	"档位 全局档": "檔位 全域檔",
	"档位 项目档": "檔位 項目檔",
	"检查中…": "檢查中…",
	"检查失败：": "檢查失敗：",
	检查更新: "檢查更新",
	"检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。": "檢查最近 24 小時的代碼與資料變更，識別運行錯誤、資料遺失與權限越界等風險，並附代碼位置與修復建議。",
	检查连接: "檢查連接",
	"检测到版本冲突，但无法读取远端版本：{0}": "偵測到版本衝突，但無法讀取遠端版本：{0}",
	"检测到版本冲突，远端版本暂不可读取": "偵測到版本衝突，遠端版本暫不可讀取",
	森林渐变: "森林漸變",
	棱镜渐变: "棱鏡漸變",
	模型: "模型",
	"模型 ID": "模型 ID",
	"模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。": "模型、MCP、命令工具、網頁抓取與搜尋、插件安裝、軟體更新下載的出口流量都將經過此代理； 應用程式介面內的網頁（渲染層）跟隨系統代理程式設定。留空時這些流量直連，不讀取系統環境變數。 本機位址（localhost、127.0.0.1、::1）始終直連。",
	模型与供应商: "模型",
	"模型与供应商、外观主题、工具权限等应用配置。": "模型、外觀主題、工具權限等應用程式配置。",
	模型与思考参数: "模型與思考參數",
	"模型与思考强度：{0} {1}": "模型與思考強度：{0} {1}",
	模型分类方式: "模型分類方式",
	"模型分类方式保存失败，已回滚：{0}": "模型分類方式儲存失敗，已回溯：{0}",
	"模型列表加载失败，可手动输入": "模型清單載入失敗，可手動輸入",
	"模型可同时存在于多个组；删除组不会删除模型。": "模型可同時存在於多個組；刪除組不會刪除模型。",
	模型已创建并加入分组: "模型已建立並加入分組",
	模型已删除: "模型已刪除",
	模型已更新: "模型已更新",
	模型已添加: "模型已新增",
	"模型指令…": "模型指令…",
	模型数量: "模型數量",
	模型组: "模型組",
	模型组列表: "模型組列表",
	模型组已创建: "模型組已建立",
	模型组已删除: "模型組已刪除",
	模型组已更新: "模型組已更新",
	模型组成员: "模型組成員",
	模型组成员已更新: "模型組成員已更新",
	模型组空状态: "模型組空狀態",
	模型组详情: "模型組詳情",
	模型能力: "模型能力",
	模型选项: "模型選項",
	模型配置: "模型配置",
	模式: "模式",
	模式名: "模式名",
	"模式名不能为空，已取消保存": "模式名稱不能為空，已取消儲存",
	"模式名重复：{0}，已取消保存": "模式名稱重複：{0}，已取消儲存",
	模式说明: "模式說明",
	模板: "範本",
	模板入口: "範本入口",
	横向分布: "橫向分佈",
	横向滚动表格: "橫向捲動表格",
	橙色: "橘色",
	次: "次",
	次数: "次數",
	"次调用 ·": "次調用 ·",
	"欢迎使用 Sunday": "歡迎使用 Sunday",
	正在: "正在",
	"正在下载 v{0}…": "正在下載 v{0}…",
	"正在下载…": "正在下載…",
	正在下载更新: "正在下載更新",
	"正在保存…": "正在保存…",
	"正在保存项目更改…": "正在儲存項目變更…",
	"正在停止…": "正在停止…",
	"正在准备完整归档，请稍候…": "正在準備完整歸檔，請稍候…",
	"正在创建…": "正在創建中…",
	正在刷新进程列表: "正在刷新進程列表",
	"正在加载…": "正在載入…",
	正在加载历史消息: "正在載入歷史消息",
	"正在加载工具模式…": "正在載入工具模式…",
	"正在加载成果库…": "正在載入成果庫…",
	正在加载更早消息: "正在載入更早訊息",
	"正在加载笔记…": "正在載入筆記…",
	正在压缩上下文: "正在壓縮上下文",
	正在同步: "正在同步",
	"正在回答…": "正在回答…",
	正在处理: "正在處理",
	"正在安装…": "正在安裝…",
	正在安装更新: "正在安裝更新",
	"正在打开…": "正在開啟…",
	"正在检查…": "正在檢查中…",
	"正在生成配对码…": "正在產生配對碼…",
	"正在读取 Sub Agent 记录...": "正在讀取 Sub Agent 記錄...",
	"正在读取…": "正在讀取…",
	"正在读取后台进程…": "正在讀取後台程序…",
	"正在读取定时任务…": "正在讀取定時任務…",
	"正在读取文本…": "正在讀取文字…",
	"正在读取记忆…": "正在讀取記憶…",
	"正在读取资料库…": "正在讀取庫…",
	"正在读取项目…": "正在讀取項目…",
	正在输出: "正在輸出",
	正常: "正常",
	正文: "正文",
	"正在运行或已暂停的子代理 {count} 个": "正在執行或已暫停的子代理 {count} 個",
	此容器: "此容器",
	"此操作不可撤销，将": "此操作不可撤銷，將",
	"此文件将交给系统默认应用处理。": "此檔案將交給系統預設應用處理。",
	此模块暂不可用: "此模組暫不可用",
	此模块未启用: "此模組未啟用",
	此电脑: "此電腦",
	此节点: "此節點",
	此节点暂不支持可视化配置: "此節點暫不支援視覺化配置",
	步: "步",
	步骤: "步驟",
	"步：": "步：",
	每: "每",
	"每 {0} 秒": "每 {0} 秒",
	每天: "每天",
	"每天 {0}": "每天 {0}",
	每月: "每月",
	"每月 {0} 日 {1}": "每月 {0} 日 {1}",
	"每月日期必须是 1 到 31": "每月日期必須是 1 到 31",
	每月第几天: "每月第幾天",
	每次新建: "每次新建",
	每行一个: "每行一個",
	"每隔（秒）": "每隔（秒）",
	水平居中: "水平居中",
	"汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。": "總結昨天以來的會談進展、完成事項與待跟進項，產生不超過 6 條的口述摘要。只讀分析，不改動文件。",
	汇聚: "匯集",
	"汇聚具名输入并收集为对象。": "匯聚具名輸入並收集為物件。",
	"没有匹配「{0}」的结果 — 换个关键词，或切到「全部」看看其他范围": "沒有符合「{0}」的結果 — 換個關鍵字，或切到「全部」看看其他範圍",
	没有匹配的供应商: "沒有配對的供應商",
	没有匹配的模型: "沒有相符的模型",
	没有匹配的模型组: "沒有相符的模型組",
	没有匹配的模式: "沒有匹配的模式",
	没有匹配的节点: "沒有符合的節點",
	没有匹配的项目: "沒有相符的項目",
	没有匹配结果: "沒有配對結果",
	没有可切换的插件模式: "沒有可切換的插件模式",
	没有找到匹配的工具: "沒有找到匹配的工具",
	没有正在登记的后台进程: "沒有正在登記的後台進程",
	没有长期后台进程: "沒有長期後台進程",
	"注入优先级（越小越靠前）": "注入優先權（越小越靠前）",
	注入到上下文的提示文本: "注入到上下文的提示文本",
	注册: "註冊",
	注释: "註釋",
	"注释.{0}": "注释.{0}",
	浅色: "淺色",
	浅色从: "淺色從",
	"浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。": "淺色使用象牙白承載石墨標記，暗色反轉為石墨底與象牙標記。",
	"浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。": "淺色使用霧藍到奶油白，暗色使用墨綠到藍黑背景，其他介面層保持中性。",
	浅色开始时间: "淺色開始時間",
	测试: "測試",
	测试失败: "測試失敗",
	测试超时: "測試逾時",
	测试通过: "測試通過",
	浏览: "瀏覽",
	"浏览…": "瀏覽…",
	"浏览了{0}个目录": "瀏覽了{0}個目錄",
	"浏览了{0}个目录…": "瀏覽了{0}個目錄…",
	浮梦: "浮夢",
	海洋渐变: "海洋漸變",
	消息附件: "訊息附件",
	淡灰: "淡灰",
	深色: "深色",
	深色从: "深色從",
	深色开始时间: "深色開始時間",
	添加: "新增",
	"添加一个 OpenAI Compatible 或其他模型供应商": "增加一個 OpenAI Compatible 或其他模式供應商",
	添加一条简短说明: "新增一則簡短說明",
	添加供应商: "新增供應商",
	添加到: "加入",
	添加到当前会话: "新增到目前會話",
	添加到收藏: "加入收藏",
	添加到文件夹: "新增到資料夾",
	添加已有模型: "新增已有模型",
	添加模型: "新增模型",
	"添加现有模型，或创建一个新模型": "新增現有模型，或建立一個新模型",
	"添加节点…": "新增節點…",
	"添加节点：{0}": "新增節點：{0}",
	添加计划: "新增計劃",
	添加附件: "新增附件",
	清单: "清單",
	清理历史: "清理歷史",
	"清理失败：{0}": "清理失敗：{0}",
	清空全部: "清空全部",
	清除: "清除",
	"清除“全部工具”后，可以单独选择需要开放的工具。": "清除「全部工具」後，可單獨選擇需要開放的工具。",
	清除搜索: "清除搜尋",
	清除节点目录搜索: "清除節點目錄搜尋",
	渐变角度: "漸層角度",
	温度: "溫度",
	激活: "激活",
	"激活会固定当前工作流 revision": "啟動會固定目前工作流程 revision",
	"激活失败：{0}": "啟動失敗：{0}",
	"激活状态刷新失败：{0}": "啟動狀態刷新失敗：{0}",
	"灰线：未上报缓存": "灰線：未上報緩存",
	灰色区压缩: "灰色區壓縮",
	灵感构思: "靈感構思",
	"点击“生成配对码”开始配对。": "點選「產生配對碼」開始配對。",
	"点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。": "點擊選項直接提交；也可以寫下你的處理方式，回車或點「發送」。",
	"点此申请 API key": "點此申請 API key",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。": "然後按下 execute-plan 的流程把目標與步驟裝進目前會話的清單，再逐步開工。",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工；方案文件的更新写回它原来的位置。": "然後按下 execute-plan 的流程把目標與步驟裝進目前會話的清單，再逐步開工；方案檔案的更新寫回它原來的位置。",
	版本不符: "版本不符",
	版本信息: "版本信息",
	"版本；切换后立即生效。": "版本；切換後立即生效。",
	状态: "狀態",
	"状态消息 (可选)": "狀態訊息 (可選)",
	"状态：{0}": "状态：{0}",
	生图: "生圖",
	"生成 {0}": "生成 {0}",
	生成中: "生成中",
	生成图片: "生成圖片",
	生成工具输入: "產生工具輸入",
	生成配对码: "產生配對碼",
	"用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。": "用 LamTools 手機端查看會話、繼續任務並處理審核。 Core 仍只監聽本機位址。",
	用一句话说明要怎么处理: "用一句話說明要怎麼處理",
	"用于侧边栏中的项目辨识。": "用於側邊欄的項目辨識。",
	用户: "用戶",
	用户上传: "使用者上傳",
	用户名: "使用者名",
	用户指令导航: "使用者指令導航",
	用户消息: "使用者訊息",
	电脑: "電腦",
	画布元素: "畫布元素",
	画布元素操作: "畫布元素操作",
	画布布局工具: "畫布佈局工具",
	界面: "介面",
	界面密度: "界面密度",
	界面语言: "介面語言",
	留空不限: "留空不限",
	留空以保留现有密钥: "留空以保留現有金鑰",
	留空时使用目录名称: "留空時使用目錄名稱",
	"留空时直连；填写后使用 http://127.0.0.1:端口。": "留空時直連；填寫後使用 http://127.0.0.1:埠。",
	登录: "登入",
	"登录 / 账号": "登入 / 帳號",
	"登录后在手机上配对，这里会列出已配对的设备。": "登入後在手機上配對，這裡會列出已配對的裝置。",
	"登录状态与已配对的设备。": "登入狀態與已配對的裝置。",
	的: "的",
	"的模型。": "的模型。",
	"目录 ": "目錄",
	"目录名 + frontmatter name": "目錄名 + frontmatter name",
	"目录路径（工作区相对或绝对）": "目錄路徑（工作區相對或絕對）",
	目标: "目標",
	目标与待发送输入: "目標與待發送輸入",
	相关设置: "相關設置",
	相册: "相冊",
	相机: "相機",
	知识关系: "知識關係",
	知识图谱: "知識圖譜",
	知识层级: "知識層級",
	知道了: "知道了",
	"确定删除“{0}”及其内部 {1} 个元素？此操作不可撤销。": "確定刪除「{0}」及其內部 {1} 個元素？此操作不可撤銷。",
	确认: "確認",
	确认删除: "確認刪除",
	确认放弃修改: "確認放棄修改",
	确认清理: "確認清理",
	确认清理队列: "確認清理隊列",
	确认移除: "確認移除",
	"确认（{0}秒）": "確認（{0}秒）",
	禁止: "禁止",
	"禁用技能 {0}": "禁用技能 {0}",
	"禁用插件 {0}": "停用外掛程式 {0}",
	离线: "離線",
	秒: "秒",
	移出组: "移出組",
	移动: "移動",
	移动端专用: "行動端專用",
	移动端快捷操作: "行動端快速操作",
	移动设备: "行動裝置",
	移除: "移除",
	"移除 {0}": "移除 {0}",
	移除计划: "移除計劃",
	移除记录: "移除記錄",
	"移除进程 ": "移除進程",
	"空值表示无条件；表达式不满足时，下游会跳过。": "空值表示無條件；表達式不滿足時，下游會跳過。",
	空闲: "閒置",
	"窗口（秒）": "視窗（秒）",
	立即安装: "立即安裝",
	端口: "端口",
	笔记: "筆記",
	笔记关系图: "筆記關係圖",
	笔记关联: "筆記關聯",
	笔记助手: "筆記助手",
	笔记库: "筆記庫",
	笔记总体关系图: "筆記總體關係圖",
	笔记文件树: "筆記文件樹",
	笔记来源: "筆記來源",
	笔记节点: "筆記節點",
	第: "第",
	"第 {0} / {1} 项": "第 {0} / {1} 項",
	"第 {0} 条用户指令，共 {1} 条": "第 {0} 條使用者指令，共 {1} 條",
	"第 {0} 条角色分配必须选择建议模型。": "第 {0} 條角色指派必須選擇建議模型。",
	"第 {0} 条角色分配的任务类型不能为空。": "第 {0} 條角色所指派的任務類型不能為空。",
	"第 {0} 条角色分配的最低思考强度不能高于最高思考强度。": "第 {0} 條角色分配的最低思考強度不能高於最高思考強度。",
	"第 {0} 行": "第 {0} 行",
	"第 {0}/{1} 段": "第 {0}/{1} 段",
	等待: "等待",
	等待中: "等待中",
	等待事件: "等待事件",
	等待你的选择: "等待你的選擇",
	"等待外部事件后继续执行。": "等待外部事件後繼續執行。",
	等待选择: "等待選擇",
	等待回答: "等待回答",
	策略: "策略",
	"策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。": "策略作用於工作流程運作；被限制的運作會進入可重試暫停態，不佔用執行槽。",
	筛选资料: "篩選資料",
	筛选资料库: "篩選庫",
	"管理 web_search 工具使用的搜索引擎内核与网络代理，保存到 websearch 插件配置后即时生效。": "管理 web_search 工具使用的搜尋引擎核心與網路代理，儲存到 websearch 外掛程式配置後即時生效。",
	"管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。": "管理事件鉤子。未信任的 Hook 不會執行，需在此審核後啟用。",
	管理你的知识: "管理你的知識",
	管理定时任务: "管理定時任務",
	"管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。": "管理已發現的 Skills，停用後不會出現在斜線指令中；新建技能寫入使用者級技能目錄，Agent 隨選 load_skill 調取。",
	"管理已安装的插件，开关它们带来的界面与工具。": "管理已安裝的插件，開關它們帶來的介面與工具。",
	"管理模型接入、供应商配置与默认模型选择。": "管理模型存取、供應商配置與預設模型選擇。",
	管理目标: "管理目標",
	类型: "類型",
	"类型 {0}": "類型 {0}",
	粉色: "粉紅色",
	粘贴: "貼上",
	"粘贴失败：当前环境无法读取剪贴板": "貼上失敗：目前環境無法讀取剪貼簿",
	系统: "系統",
	系统打开: "系統打開",
	"系统提示词…": "系統提示詞…",
	索引可用: "索引可用",
	索引异常: "索引異常",
	索引未检查: "索引未檢查",
	紧凑: "緊湊",
	紫色: "紫色",
	紫蓝渐变: "紫藍漸變",
	红色: "紅色",
	纯文本: "純文本",
	"纯色层级更安静，并以清晰实线边界维持长期工作的可读性。": "純色層級較安靜，並以清晰實線邊界維持長期工作的可讀性。",
	纵向分布: "縱向分佈",
	终止进程: "終止進程",
	"终止进程 ": "終止進程",
	"终止这个回合？": "終止這個回合？",
	结束: "結束",
	结果: "結果",
	"结果上限 limit（默认 5，1-20）": "結果上限 limit（預設 5，1-20）",
	结论: "結論",
	"给 Sunday 发送任务...": "給 Sunday 發送任務...",
	"继承全局策略：{0}": "繼承全域策略：{0}",
	"继承全局（当前：{0}）": "繼承全域（目前：{0}）",
	继续编辑: "繼續編輯",
	"继续问…": "繼續問…",
	绿色: "綠色",
	缓存: "緩存",
	缓存命中率: "快取命中率",
	"缓存（": "快取（",
	编排: "編排",
	编辑: "編輯",
	"编辑 {0}": "編輯 {0}",
	编辑供应商: "編輯供應商",
	编辑右侧面板布局: "編輯右側面板佈局",
	编辑定时任务: "編輯定時任務",
	编辑工作流: "編輯工作流程",
	编辑待发送内容: "編輯待寄內容",
	编辑文件: "編輯文件",
	编辑条件: "編輯條件",
	编辑模型: "編輯模型",
	编辑消息: "編輯訊息",
	编辑笔记全文: "編輯筆記全文",
	编辑节点: "編輯節點",
	编辑连线条件: "編輯連線條件",
	缩小: "縮小",
	缺少可打开的附件标识: "缺少可開啟的附件標識",
	缺少可读取的文本路径: "缺少可讀取的文字路徑",
	网关: "網關",
	网关运行中: "閘道運作中",
	网格吸附已关闭: "網格吸附已關閉",
	网格吸附已开启: "網格吸附已開啟",
	网格视图: "網格視圖",
	置顶: "置頂",
	置顶会话: "置頂會話",
	置顶项目: "置頂項目",
	翻译: "翻譯",
	耗时: "耗時",
	"耗时 ": "耗時",
	"耗时 {0} s": "耗時 {0} s",
	"耗时 —": "耗時 —",
	聊天: "聊天",
	聚焦选中: "聚焦選中",
	"背景板 / 侧边栏": "背景板 / 側邊欄",
	能力: "能力",
	能力分类: "能力分類",
	"能力的模型。保存到": "能力的模型。保存到",
	自动: "自動",
	自动检查: "自動檢查",
	"自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。": "自動模式依 WSL → Git Bash → PowerShell 的順序選擇可用 shell；手動選擇的 shell 不可用時也會依此順序回退。",
	"自动继续的内存阈值（GB）": "自動繼續的記憶體閾值（GB）",
	"自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。": "自動繼續的記憶體閾值（GB）：可用記憶體 = 實體記憶體 + 頁面檔案還能分配的量。調高更保守，但要等更久。",
	"自动（内置声明）": "自動（內建聲明）",
	自定义: "自訂",
	"自定义工作流节点。": "自訂工作流程節點。",
	自定义接口: "自訂介面",
	自定义证书: "自訂證書",
	自检: "自檢",
	"自迭代 (loop)": "自迭代 (loop)",
	节流: "節流",
	"节流 {0}s": "節流 {0}s",
	节点: "節點",
	"节点 {0} · 画布元素 {1}": "節點 {0} · 畫布元素 {1}",
	节点分类: "節點分類",
	节点参数: "節點參數",
	节点已对齐: "節點已對齊",
	节点已横向分布: "節點已橫向分佈",
	节点已纵向分布: "節點已縱向分佈",
	节点标题: "節點標題",
	节点目录: "節點目錄",
	节点目录筛选: "節點目錄篩選",
	"英 {0} 美 {1}": "英 {0} 美 {1}",
	"范围 {0}-{1} 行": "範圍 {0}-{1} 行",
	"范围进度，尚未独立评估": "範圍進度，尚未獨立評估",
	草稿: "草稿",
	莓果渐变: "莓果漸變",
	"莓紫、灰蓝与青绿的横向渐变。": "莓紫、灰藍與青綠的橫向漸層。",
	获取网页: "取得網頁",
	"获取网页 {0}": "取得網頁 {0}",
	蓝色: "藍色",
	行: "行",
	行内代码: "行內程式碼",
	"补齐缺少的端口（": "補齊缺少的連接埠（",
	表单说明: "表單說明",
	表格: "表格",
	覆盖: "覆蓋",
	"规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。": "規則會統一追加到 sub_agent 呼叫紀律之後。任務類型配對時，為主 Agent 提供建議的子代理人類型、模型與思考強度範圍。",
	视图切换: "視圖切換",
	视觉: "視覺",
	角色: "角色",
	角色分配: "角色分配",
	解释: "解釋",
	解锁: "解鎖",
	"解锁 {0}": "解鎖 {0}",
	触发器: "觸發器",
	"触发器 ID 不能为空": "觸發器 ID 不能為空",
	"触发器 ID 已存在：{0}": "觸發器 ID 已存在：{0}",
	"触发器 {0}": "觸發器 {0}",
	触发器列表: "觸發器列表",
	"触发器已保存。": "觸發器已儲存。",
	触发器激活: "觸發器激活",
	触发器类型: "觸發器類型",
	计划: "計劃",
	计划更新失败: "計畫更新失敗",
	"计划：{0} 步": "計畫：{0} 步",
	"让 agent 完成的目标…": "讓 agent 完成的目標…",
	记忆: "記憶",
	记忆名称: "記憶名稱",
	"记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。": "記憶就是普通文件：寫在這裡的，助手在之後的每個會話裡都能讀到。",
	记忆档位: "記憶檔位",
	记忆续跑: "記憶續跑",
	记忆编辑: "記憶編輯",
	记忆阅读: "記憶閱讀",
	设为预设首选: "設為預設首選",
	设备: "設備",
	"设备 ID": "設備 ID",
	设备与工作环境: "設備與工作環境",
	设置: "設定",
	设置分区: "設定分區",
	"设置界面语言、网络连接与运行偏好。": "設定介面語言、網路連線與執行偏好。",
	设计创作: "設計創作",
	询问: "詢問",
	该供应商下还没有模型: "該供應商下方還沒有模型",
	该目录已在列表中: "該目錄已在清單中",
	该组还没有模型: "該組還沒有模型",
	该连线已经存在: "該連線已經存在",
	详情: "詳情",
	详细调整: "詳細調整",
	"说明何时使用，供 Agent 检索": "說明何時使用，以供 Agent 檢索",
	"说明希望如何处理…": "說明希望如何處理…",
	"请先保存工作流并解决冲突，再激活触发器": "請先儲存工作流程並解決衝突，再啟動觸發器",
	"请先新增供应商，再添加模型": "請先新增供應商，再新增模型",
	"请先添加供应商/模型（设置 → 模型与供应商）": "請先新增供應商/模型（設定 → 模型）",
	请先选择会话: "請先選擇會話",
	请先选择供应商: "請先選擇供應商",
	"请填写必填输入：{0}": "請填入必填輸入：{0}",
	请求中: "請求中",
	"请输入有效 JSON：{0}": "請輸入有效 JSON：{0}",
	"请选择完整归档的保存位置…": "請選擇完整歸檔的保存位置…",
	读: "讀",
	"读取 {0}": "讀取 {0}",
	读取中: "讀取中",
	"读取中…": "讀取中…",
	"读取了{0}个文件": "讀取了{0}個文件",
	"读取了{0}个文件…": "讀取了{0}個檔案…",
	读取失败: "讀取失敗",
	读取定时任务失败: "讀取定時任務失敗",
	读取文件: "讀取文件",
	"读取运行记录…": "讀取運轉記錄…",
	"读取运行详情失败：{0}": "讀取運行詳情失敗：{0}",
	调度: "調度",
	调度方式: "調度方式",
	调整主界面: "調整主介面",
	"调整内容区的信息密度。": "調整內容區的資訊密度。",
	调整子代理面板宽度: "調整子代理面板寬度",
	调整宽高: "調整寬高",
	调整控件: "調整控件",
	"调整此任务的执行时间、指令和运行方式。": "調整此任務的執行時間、指令和運作方式。",
	调整背景板和侧边栏: "調整背景板與側邊欄",
	调整输入栏: "調整輸入欄",
	调用: "調用",
	"调用 MCP 工具": "呼叫 MCP 工具",
	"调用一次 (none)": "呼叫一次 (none)",
	"调用了{0}个工具": "呼叫了{0}個工具",
	"调用另一个工作流。": "呼叫另一個工作流程。",
	"调用智能体执行任务，可按需使用工具。": "呼叫智能體執行任務,可按需使用工具。",
	"象牙白与石墨灰的纯色主题。": "象牙白與石墨灰的純色主題。",
	负责人: "負責人",
	"负责逐工具能力边界，不在这里重复配置。": "負責逐工具能力邊界，不在這裡重複配置。",
	账号: "帳號",
	账号与设备: "帳號與設備",
	"账号绑定命令将在桌面 Tauri 运行时启用。": "帳號綁定指令將在桌面 Tauri 執行時啟用。",
	资料: "資料",
	"资料 / 记忆 / 方案 — 一个入口三块内容。": "資料 / 記憶 / 方案 — 一個入口三塊內容。",
	资料库: "庫",
	"资料库 › {0}": "庫 › {0}",
	"资料库 › 资料": "庫 › 資料",
	资料库分区: "庫分區",
	资料库还是空的: "庫還是空的",
	资源: "資源",
	超时: "逾時",
	"超时 ": "逾時",
	"超时 (秒)": "逾時 (秒)",
	"超时秒数 timeout": "超時秒數 timeout",
	"超时（秒）": "超時（秒）",
	超高: "超高",
	跟随系统: "跟隨系統",
	"跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。": "跨項目共享的記憶 — 模型在會話裡讀它，你在這裡整理它。",
	"跨项目查找会话、消息、方案与文件。": "跨專案尋找會話、訊息、方案與文件。",
	路径: "路徑",
	跳过: "跳過",
	转到注册: "前往註冊",
	转换: "轉換",
	"转换（兼容）": "轉換(相容)",
	轻: "輕",
	输入: "輸入",
	"输入你的回答…": "輸入你的答案…",
	"输入关键词搜索任务、插件或文件": "輸入關鍵字搜尋任務、外掛程式或文件",
	"输入内容...": "輸入內容...",
	"输入内容…": "輸入內容…",
	"输入必须是对象：{0}": "輸入必須是物件：{0}",
	"输入必须是数字：{0}": "輸入必須是數字：{0}",
	"输入必须是数组：{0}": "輸入必須是數組：{0}",
	输入栏: "輸入欄",
	"输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。": "輸入框裡的「詢問 / 自動 / 完全存取」是目前會話的即時狀態；切換到自動或完全存取會立即放行待審批操作。",
	输入端口: "輸入端口",
	输入端口类型: "輸入埠類型",
	输入输出: "輸入輸出",
	输出: "輸出",
	"输出工作流结果。": "輸出工作流程結果。",
	"输出格式（文本说明，可选）": "輸出格式（文字說明，可選）",
	输出端口: "輸出端口",
	"输出端口 = JSON 字段（强制 JSON 输出）": "輸出埠 = JSON 欄位（強制 JSON 輸出）",
	"输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）": "輸出埠 = JSON 鍵名（stdout 是 JSON 時自動分割）",
	"输出端口 = 给同名变量赋值": "輸出埠 = 為同名變數賦值",
	输出端口类型: "輸出埠類型",
	"输出预设的常量值。": "输出预设的常量值。",
	过程: "過程",
	过程图标颜色: "過程圖示顏色",
	过程图标颜色十六进制值: "過程圖示顏色十六進位值",
	运行: "運行",
	"运行 ID": "運行 ID",
	"运行 {0}": "運行 {0}",
	"运行一条 Shell 命令。": "运行一条 Shell 命令。",
	运行与适配: "運轉與適配",
	运行中: "執行中",
	"运行中…": "運行中…",
	运行事件: "運行事件",
	运行历史: "運行歷史",
	运行命令: "運行指令",
	运行失败: "運行失敗",
	"运行失败：{0}": "運行失敗：{0}",
	运行整个工作流: "運行整個工作流程",
	运行时: "運行時",
	运行模式: "運行模式",
	运行模式与权限参数: "運作模式與權限參數",
	"运行模式与权限：{0} · {1}": "運作模式與權限：{0} · {1}",
	运行模式选项: "運行模式選項",
	运行此节点: "運行此節點",
	运行状态: "運作狀態",
	运行策略: "運行策略",
	运行结果: "運行結果",
	"运行节点…": "運行節點…",
	运行详情: "運行詳情",
	运行输入: "運行輸入",
	"运行输入必须是 JSON 对象": "運行輸入必須是 JSON 對象",
	"运行输入（JSON，可选）": "運行輸入（JSON，可選）",
	运行进度: "運行進度",
	运行链路: "運行鏈路",
	返回: "返回",
	返回主会话: "返回主會話",
	返回主界面: "返回主介面",
	返回会话: "返回會話",
	"返回会话（Esc）": "返回會話（Esc）",
	返回列表: "返回列表",
	返回学习: "返回學習",
	返回对话: "返回對話",
	返回登录: "返回登入",
	还原: "還原",
	"还没有 Markdown 笔记。": "還沒有 Markdown 筆記。",
	还没有供应商: "還沒有供應商",
	"还没有内容。": "還沒有內容。",
	还没有定时任务: "還沒有定時任務",
	还没有工作模式: "還沒有工作模式",
	"还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。": "還沒有歸檔 — 在文件卡的選單裡「歸到資料夾」就會出現在這裡。",
	"还没有摘要 — 打开写第一段。": "還沒有摘要 — 開啟寫第一段。",
	"还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。": "還沒有收藏的方案 — 在方案卡的選單裡「加入到收藏」。",
	还没有方案: "還沒有方案",
	还没有模型组: "還沒有模型組",
	还没有运行历史: "還沒有運行歷史",
	"还没有运行记录。": "還沒有運行記錄。",
	还没有项目有记忆: "還沒有項目有記憶",
	这一层还没有文件: "這一層還沒有文件",
	这一行没有可打开的文件路径: "這一行沒有可開啟的檔案路徑",
	"这个子代理还没有产生过程记录。": "這個子代理還沒有產生過程記錄。",
	这个文件夹还是空的: "這個資料夾還是空的",
	"这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。": "這個資料夾還是空的 — 點右上角「新建方案」，它會建在這裡。",
	"这个文件夹里还没有记忆文件。": "這個資料夾裡還沒有記憶檔。",
	这个模式可以使用全部工具: "這個模式可以使用全部工具",
	"这个状态下暂无任务。": "這個狀態下暫無任務。",
	"这个状态下暂无方案。": "這個狀態下暫無方案。",
	"这个账号还没有已登记设备。": "這個帳號還沒有已登記設備。",
	"这些信息用于连接模型服务。": "這些資訊用於連結模型服務。",
	"这些设置只作为新会话的起点，不会静默改变已经运行的任务。": "這些設定只作為新會話的起點，不會靜默改變已經執行的任務。",
	这条消息没有可用的回合: "這則訊息沒有可用的回合",
	"这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。": "這段引用在文件中出現多次，無法安全鎖定；請在編輯態框選。",
	这片记忆还是空的: "這片記憶還是空的",
	"这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。": "這裡還沒有可顯示的知識點；先在學習會話中讓 AI 建立知識網。",
	这里还没有子文件夹: "這裡還沒有子資料夾",
	进度: "進度",
	进程日志: "進程日誌",
	进行中: "進行中",
	进阶: "進階",
	"远程图片仅在 Study 中显示：{0}": "遠端圖片僅在 Study 中顯示：{0}",
	"远端工作流有更新，请处理冲突": "遠端工作流程有更新，請處理衝突",
	"连接一个可用的模型服务。": "連結一個可用的模型服務。",
	连接信息: "連線訊息",
	连接异常: "連線異常",
	连线已更新: "連線已更新",
	迭代模式: "迭代模式",
	"追加加载的文件（addition）": "追加載入的檔案（addition）",
	退出条件: "退出條件",
	"退出条件（Python 表达式）": "退出條件（Python 表達式）",
	"退出码 ": "退出碼",
	"退出码 {0}": "退出碼 {0}",
	退出账号: "退出帳號",
	"适合长时间处理任务与配置。": "適合長時間處理任務與配置。",
	适应画布: "適應畫布",
	"选中文字后右键，即可解释、询问或翻译。": "選取文字後右鍵，即可解釋、詢問或翻譯。",
	选填: "選填",
	"选填，如限速、用途、注意事项等": "選填，如限速、用途、注意事項等",
	"选填，留空时使用模型 ID": "選填，留空時使用模型 ID",
	选择: "選擇",
	"选择 {0}": "選擇 {0}",
	"选择一个工作目录，系统会为项目准备基础配置。": "選擇一個工作目錄，系統會為專案準備基礎配置。",
	"选择一个已登记的项目继续工作。": "選擇一個已登記的項目繼續工作。",
	"选择主题随系统变化、固定在一个模式，或按时段自动切换。": "選擇主題隨系統變化、固定在一個模式，或依時段自動切換。",
	选择供应商: "選擇供應商",
	"选择官方模板，或手动填写服务信息。": "選擇官方模板，或手動填寫服務資訊。",
	选择工作模式: "選擇工作模式",
	"选择工作流 JSON 文件": "選擇工作流程 JSON 文件",
	选择工作环境: "選擇工作環境",
	选择已有照片: "選擇已有照片",
	选择已登记项目: "選擇已登記項目",
	"选择应用界面的显示语言。不会更改对话内容或模型的回答语言。": "選擇應用程式介面的顯示語言。不會更改對話內容或模型的回答語言。",
	选择或填写项目地址: "選擇或填寫項目地址",
	"选择或输入模型 ID": "選擇或輸入模型 ID",
	选择模型: "選擇模型",
	选择模型组: "選擇模型組",
	"选择模板后，按官方页面申请 API key；免费模型通常有额度或容量限制。": "選擇範本後，按官方頁面申請 API key；免費模型通常有額度或容量限制。",
	选择此目录: "選擇此目錄",
	选择目录: "選擇目錄",
	选择要放入: "選擇要放入",
	选择附件来源: "選擇附件來源",
	选择项目: "選擇項目",
	"选择项目后查看成果库。": "選擇專案後查看成果庫。",
	选择项目目录: "選擇項目目錄",
	透明度: "透明度",
	"逐工具白名单、工具模式与扩展权限分别管理": "逐工具白名單、工具模式與擴充權限分別管理",
	通用: "通用",
	通用文件夹: "通用資料夾",
	通过对话创建笔记: "透過對話創造筆記",
	速率限制: "速率限制",
	"遍历数组 (map)": "遍歷陣列 (map)",
	配图: "配圖",
	配对新设备: "配對新設備",
	配置: "配置",
	"配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。": "設定 sub_agent 呼叫提示詞，指導主 Agent 如何與何時委派子 Agent（model/mode 等）。",
	"配置任务的执行时间、指令和运行方式。": "設定任務的執行時間、指令和運作方式。",
	配置完成: "配置完成",
	配置文件: "設定文件",
	配置模型供应商: "配置模型供應商",
	采用远端版本: "採用遠端版本",
	重做: "重做",
	"重做（Ctrl/Cmd+Shift+Z）": "重做（Ctrl/Cmd+Shift+Z）",
	重合区域: "重疊區域",
	"重合区域：": "重疊區域：",
	重命名: "重新命名",
	"重命名会话 {0}": "重新命名會話 {0}",
	"重命名失败：{0}": "重新命名失敗：{0}",
	重命名方案: "重新命名方案",
	重命名模型组: "重新命名模型組",
	重新下载: "重新下載",
	重新显示首次引导: "重新顯示首次引導",
	重新检查: "重新檢查",
	重试: "重試",
	重试中: "重試中",
	"重试中 {0}/{1}": "重試中 {0}/{1}",
	重试次数: "重試次數",
	重连中: "重連中",
	钩子: "鉤子",
	钩子·已信任: "鉤子·已信任",
	链接: "鏈接",
	锁定选中内容: "鎖定選取內容",
	错误处理: "錯誤處理",
	错误输出: "錯誤輸出",
	"长期驻留（轮次结束后继续运行）": "長期駐留（輪次結束後繼續運轉）",
	问题: "問題",
	间隔: "間隔",
	间隔秒数: "間隔秒數",
	"间隔触发器需要 every_seconds": "間隔觸發器需要 every_seconds",
	"阈值需要是 0.5 到 1024 之间的数字（GB）": "閾值需要是 0.5 到 1024 之間的數字（GB）",
	"队列 ID": "佇列 ID",
	队列与历史: "隊列與歷史",
	队列优先级: "佇列優先權",
	"队列刷新失败：{0}": "佇列刷新失敗：{0}",
	队列视图: "佇列視圖",
	队列运行详情: "佇列運行詳情",
	防抖: "防手震",
	"防抖 {0}s": "防手震 {0}s",
	防抖模式: "防手震模式",
	附件: "附件",
	"附件上传失败：{0}": "附件上傳失敗：{0}",
	附件预览失败: "附件預覽失敗",
	附件预览已读取: "附件預覽已讀取",
	降级输出: "降級輸出",
	降级输出端口: "降級輸出埠",
	降级默认值: "降級預設值",
	"限速 {0}/{1}s": "限速 {0}/{1}s",
	随轮次结束清理: "隨輪次結束清理",
	隐藏已移除: "隱藏已移除",
	"雾蓝到奶油白的浅色渐变。": "霧藍到奶油白的淺色漸層。",
	需压缩: "需壓縮",
	需确认: "需確認",
	需要你确认: "需要你確認",
	"需要你确认，共 {0} 项": "需要你確認，共 {0} 項",
	青色: "青色",
	面板: "面板",
	音视频: "影音",
	顶对齐: "頂對齊",
	项: "項",
	项目: "專案",
	"项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。": "專案作用域的 sub_agent 配置，會覆寫全域配置。留空保存可回退到繼承的全域 / 內建預設。",
	"项目作用域的元信息与 AGENTS.md 指令。": "計畫作用域的元資訊與 AGENTS.md 指令。",
	"项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。": "專案保存工作目錄、會話和運行配置。你也可以開啟已使用過的目錄。",
	"项目列表不可用，无法进入项目记忆": "項目清單不可用，無法進入項目記憶",
	项目名称: "項目名稱",
	项目图标: "項目圖標",
	项目图标与颜色: "項目圖示與顏色",
	项目地址: "項目地址",
	项目外观: "項目外觀",
	"项目将保存在当前设备。": "項目將保存在目前設備。",
	"项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。": "項目尚未配置覆蓋；選擇策略並儲存後，僅寫入目前項目。",
	项目成果库: "計畫成果庫",
	项目操作: "專案操作",
	"项目文件和自动生成的 AGENTS.md 将存放在此目录。": "專案檔案和自動產生的 AGENTS.md 將存放在此目錄中。",
	项目目录: "專案目錄",
	项目规则: "項目規則",
	项目记忆: "項目記憶",
	"项目记忆按项目归档 — 先选一个项目，再整理它的记忆。": "項目記憶依項目歸檔 — 先選一個項目，再整理它的記憶。",
	项目设置: "項目設置",
	项目设置分区: "專案設定分區",
	"项目里进出的文件 — 用户上传、中间产物与最终产物。": "專案裡進出的檔案 — 使用者上傳、中間產物與最終產物。",
	项目颜色: "項目顏色",
	"项；文件本身不会被删除。": "項；檔案本身不會被刪除。",
	预览: "預覽",
	"预览 {0}": "預覽 {0}",
	预览排版: "預覽排版",
	预设颜色: "預設顏色",
	预设首选: "預設首選",
	频率: "頻率",
	颜色: "顏色",
	"颜色节点、透明度与界面密度": "顏色節點、透明度與介面密度",
	风险扫描: "風險掃描",
	首个执行: "首個執行",
	首次任务: "首次任務",
	首次使用引导: "首次使用引導",
	验证: "驗證",
	验证未通过: "驗證未通過",
	高: "高",
	"高危命令默认需要运行前确认（自动批准模式除外）。": "高危險指令預設需要執行前確認（自動核准模式除外）。",
	高级工具白名单: "進階工具白名單",
	高级设置: "進階設置",
	高级调整: "進階調整",
	"高级适配 JSON": "高階適配 JSON",
	"高级适配 JSON 必须是对象": "高階適配 JSON 必須是對象",
	默认: "預設",
	"默认值（空=哨兵跳过）": "預設值（空=哨兵跳過）",
	"默认内核 provider": "預設核心 provider",
	默认多模态解析模型: "預設多模態解析模型",
	"默认审批策略保存失败，已回滚：{0}": "預設審核策略儲存失敗，已回溯：{0}",
	默认搜索内核: "預設搜尋內核",
	默认模型: "預設模型",
	"（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。 外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。": "（國內可達，建議）· bing（英文/分詞正常詞可用）· ddg（海外備胎）。 外部工具（GPL/AGPL 等獨立進程）經 subprocess/http 接入，需手動設定 JSONC。",
	"（支持": "（支持",
	"（无）": "（無）",
	"（日志为空）": "（日誌為空）",
	"（暂无日志输出）": "（暫無日誌輸出）",
	"（检查网络后重试）": "（檢查網路後重試）",
	"（空指令）": "（空指令）",
	"（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "（統一配置目錄）。專案級規則請在「專案設定 → 專案」內編輯，兩者會相加註入系統提示字。",
	"（还没有内容）": "（還沒有內容）",
	"（还没有摘要）": "（還沒有摘要）",
	"（默认 work_root）": "（預設 work_root）",
	"（默认模型）": "（預設模型）",
	"＋ 新增模型": "＋ 新增模型",
	"＋ 新建供应商": "＋ 新建供應商",
	"＋ 追加文件": "＋ 追加文件",
	"，且无法恢复。": "，且無法恢復。",
	"，但没有适用于本平台的安装包（可到发布页查看）": "，但沒有適用於本平台的安裝包（可到發布頁查看）",
	"，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：": "，全域疊加到每個工作區（工作區自己的 load_context.jsonc 在其上疊加）。 CLI：",
	"，移动端为应用私有技能目录）。": "，行動端為應用私有技能目錄）。",
	"，里面的条目也会一起删掉": "，裡面的條目也會一起刪掉",
	"：暂无可配置参数": "：暫無可設定參數",
	"thinking.off": "關閉",
	"保存修改？": "儲存修改？",
	丢弃修改: "捨棄修改",
	"未能保存，请检查修改后重试。": "無法儲存，請檢查修改後重試。",
	自动恢复阈值: "自動恢復門檻",
	子代理指南: "子代理指南",
	代理地址: "代理位址",
	直连地址: "直接連線位址",
	"CA 证书": "CA 憑證",
	"请填写必填项并检查输入格式。": "請填寫必填欄位並檢查輸入格式。",
	"配置已保存，但未能完成同步：{0}": "設定已儲存，但無法完成同步：{0}",
	继续运行: "繼續執行",
	重试启动: "重試啟動",
	"新插件系统（预览）": "新外掛系統（預覽）",
	"与当前插件页互不影响。这里只验证清单、启停和卸载。": "與目前外掛頁面互不影響。這裡只驗證清單、啟停和卸載。",
	"还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "還沒有外掛。在外掛根目錄放一個只有 name 和 version 的 plugin.json 就會出現。",
	禁用: "停用",
	没有声明能力: "沒有宣告能力",
	"声明错误：{0}": "宣告錯誤：{0}",
	"加载错误 {0}": "載入錯誤 {0}",
	"卸载 {0}？data 目录会保留。": "卸載 {0}？data 目錄會保留。",
	"已卸载 {0}，data 目录保留。": "已卸載 {0}，data 目錄保留。",
	会修改数据: "會修改資料",
	"sha256（可选）": "sha256（可選）",
	"{0} 条匹配": "{0} 條匹配",
	"内核（不可替换）": "核心（不可替換）",
	"加载配置中…": "載入設定中…",
	压缩包: "壓縮包",
	可替换模块: "可替換模組",
	"字段 {0} 需要合法的 JSON。": "欄位 {0} 需要合法的 JSON。",
	"已保存 {0} 的配置。": "已儲存 {0} 的設定。",
	"当前环境没有桌面窗口，插件窗口只能在桌面端打开。": "目前環境沒有桌面視窗，插件視窗只能在桌面端開啟。",
	"打开窗口 {0}": "開啟視窗 {0}",
	收起配置: "收起設定",
	"更新（同名替换，data 保留）": "更新（同名替換，data 保留）",
	"查行为表：模块名或片段（如 prompt、plugin_system.host）": "查行為表：模組名或片段（如 prompt、plugin_system.host）",
	查询: "查詢",
	没有声明依赖: "沒有宣告依賴",
	"清单、启停、安装、更新与卸载都在这里。": "清單、啟停、安裝、更新與解除安裝都在這裡。",
	"确定执行 {0}？": "確定執行 {0}？",
	"确定执行 {0}？该操作会修改数据。": "確定執行 {0}？該操作會修改資料。",
	"自定义配置面板加载失败：{0}": "自訂設定面板載入失敗：{0}",
	"这个插件没有可配置项。": "這個插件沒有可設定項。",
	筛选文档: "篩選文檔",
	"Wiki 目录": "Wiki 目錄",
	目录: "目錄",
	文档导航: "文檔導覽",
	没有匹配的文档: "沒有符合的文檔",
	没有可用的文档: "沒有可用的文檔",
	"data 目录会保留": "data 目錄會保留",
	"{0} / {1}": "{0} / {1}",
	"{0} 个已启用": "{0} 個已啟用",
	"{0} 个插件": "{0} 個外掛",
	"{0} 个需要处理": "{0} 個需要處理",
	"依赖：{0}": "依賴：{0}",
	入口: "入口",
	全局: "全域",
	"分屏打开 {0}": "分割畫面開啟 {0}",
	"卸载 {0}": "卸載 {0}",
	"卸载插件？": "卸載外掛？",
	启动失败: "啟動失敗",
	"启用 {0}": "啟用 {0}",
	"在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "在外掛根目錄放一個只有 name 和 version 的 plugin.json 就會出現。",
	声明错误: "宣告錯誤",
	复制安装路径: "複製安裝路徑",
	安全模式已跳过: "安全模式已略過",
	安装或更新插件: "安裝或更新外掛",
	安装来源: "安裝來源",
	安装来源地址: "安裝來源位址",
	已停止: "已停止",
	"已安装 {0}": "已安裝 {0}",
	"已更新 {0}": "已更新 {0}",
	"换个关键词，或清除筛选条件。": "換個關鍵字，或清除篩選條件。",
	"插件代码已更新，重启应用后模块覆盖和全局脚本将生效。": "外掛程式碼已更新，重新啟動應用程式後模組覆蓋與全域腳本將生效。",
	插件配置: "外掛設定",
	"搜索插件、能力或路径": "搜尋外掛、能力或路徑",
	收起安装: "收起安裝",
	"更新会覆盖同名插件，data 目录会保留。": "更新會覆蓋同名外掛，data 目錄會保留。",
	未声明能力: "未宣告能力",
	"本地目录、压缩包或链接，三种来源共用一条流程。": "本機目錄、壓縮檔或連結，三種來源共用同一流程。",
	查询行为表: "查詢行為表",
	"模块名或片段（如 prompt、plugin_system.host）": "模組名稱或片段（如 prompt、plugin_system.host）",
	正在切换: "正在切換",
	正在启动: "正在啟動",
	"没有加载错误。": "沒有載入錯誤。",
	没有匹配的插件: "沒有符合的外掛",
	没有描述: "沒有描述",
	清除筛选: "清除篩選",
	"禁用 {0}": "停用 {0}",
	等待启动: "等待啟動",
	筛选插件: "篩選外掛",
	缺失: "缺少",
	行为表查询与加载错误: "行為表查詢與載入錯誤",
	诊断与行为表: "診斷與行為表",
	运行就绪: "執行就緒",
	还没有插件: "還沒有外掛",
	需要处理: "需要處理",
	"（缺 {0}，可用 pip 安装；不阻止安装）": "（缺 {0}，可用 pip 安裝；不阻止安裝）",
	自定义配置面板加载失败: "自訂設定面板載入失敗",
	无法加载插件: "無法載入外掛",
	"检查后台连接后再试一次。": "檢查後台連線後再試一次。",
	再试一次: "再試一次",
	"QQ robot": "QQ robot",
	插件页面: "插件页面",
	源代码与许可证: "源代码与许可证",
	"当前显示缓存目录；安装时会重新核对 GitHub 最新发布。": "当前显示缓存目录；安装时会重新核对 GitHub 最新发布。",
	插件市场: "插件市场",
	"从 GitHub 安装插件": "从 GitHub 安装插件",
	插件能力: "插件能力",
	"暂时无法获取市场目录，请检查网络后重试。": "暂时无法获取市场目录，请检查网络后重试。",
	"正在连接插件市场…": "正在连接插件市场…",
	版本暂不可用: "版本暂不可用",
	"独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。": "独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。",
	视频与字幕检索: "视频与字幕检索",
	内容与信息: "内容与信息",
	重新连接: "重新连接",
	每日内容简报: "每日内容简报",
	消息与协作: "消息与协作",
	刷B站: "刷B站",
	"QQ 私聊与群聊": "QQ 私聊与群聊",
	已安装: "已安装",
	"下载并校验中…": "下载并校验中…",
	持久会话: "持久会话",
	消息提醒: "消息提醒",
	暂不可用: "暂不可用",
	changed: "changed",
	有新版本: "有新版本",
	审批与文件投递: "审批与文件投递",
	"插件已安装，可在“已安装”中配置和管理。": "插件已安装，可在“已安装”中配置和管理。",
	"把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。": "把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。",
	"读取视频字幕、整理值得看的内容，生成日报并发送提醒。": "读取视频字幕、整理值得看的内容，生成日报并发送提醒。",
	"Assistant 显示": "Assistant 顯示",
	"只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。": "只影響介面顯示：是否使用氣泡、是否自動拆分，以及顯示的名稱與頭像；對話記錄、上下文和訊息協定都不變。",
	"Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。": "Assistant 可選擇是否使用訊息氣泡，開啟後回覆以氣泡呈現，關閉時保持無邊框正文。",
	使用消息气泡: "使用訊息氣泡",
	"自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。": "自動氣泡拆分會把一則長回覆依段落與標題拆成多個氣泡；程式碼區塊、公式和表格保持完整，關閉後整則回覆只顯示為一個氣泡。",
	自动气泡拆分: "自動氣泡拆分",
	"显示名称：留空时使用默认名称（Assistant）。": "顯示名稱：留空時使用預設名稱（Assistant）。",
	"例如 Sunday": "例如 Sunday",
	"头像：上传一张图片并调整裁切；留空时显示名称首字母。": "頭像：上傳一張圖片並調整裁切；留空時顯示名稱首字母。",
	头像: "頭像",
	"例如 https://example.com/avatar.png": "例如 https://example.com/avatar.png",
	图层: "圖層",
	元素: "元素",
	未分层: "未分層",
	"在「{0}」内": "在「{0}」內",
	父层自动: "父層自動",
	"父层 z={0}": "父層 z={0}",
	"自动层（按文档顺序，后绘制的在上）": "層內自動子層（同一塊裡按文件順序，後繪製的在上）",
	关闭编辑器: "關閉編輯器",
	收起面板: "收起面板",
	展开面板: "展開面板",
	编辑模式: "編輯模式",
	"编辑模式已关闭，界面可正常操作。": "編輯模式已關閉，介面可正常操作。",
	不保存修改并退出: "不儲存修改並退出",
	"在界面上点选组件，或从下面选择。": "在介面上點選元件，或從下方選擇。",
	"正在预览真实界面，修改会立即生效。": "正在預覽真實介面，修改會立即生效。",
	属性: "屬性",
	"先选择一个组件。": "先選擇一個元件。",
	"这个组件是业务入口，只能调整外观，不能移动或隐藏。": "這個元件是業務入口，只能調整外觀，不能移動或隱藏。",
	文字颜色: "文字顏色",
	背景颜色: "背景顏色",
	"自动（跟随页面）": "自動（跟隨頁面）",
	锚点: "錨點",
	横向: "橫向",
	纵向: "縱向",
	不锚定: "不錨定",
	横向锚点: "橫向錨點",
	纵向锚点: "縱向錨點",
	横向距离: "橫向距離",
	纵向距离: "縱向距離",
	"锚点=到父容器某条边的距离，不会小于 0。": "錨點=到父容器某條邊的距離，不會小於 0。",
	自定义颜色: "自訂顏色",
	透明: "透明",
	主区域底色: "主區域底色",
	主区域柔和底色: "主區域柔和底色",
	应用底色: "應用底色",
	输入区底色: "輸入區底色",
	控件底色: "控件底色",
	背景颜色令牌无效: "背景顏色令牌無效",
	圆角: "圓角",
	间距: "間距",
	字号: "字號",
	层级: "層級",
	"显示/隐藏图层": "顯示/隱藏圖層",
	"锁定/解锁图层": "鎖定/解鎖圖層",
	"第 {0} 层": "第 {0} 層",
	显示: "顯示",
	清除这个组件的修改: "清除這個元件的修改",
	有未发布修改: "有未發佈修改",
	已同步: "已同步",
	发布: "發佈",
	受保护: "受保護",
	仅外观: "僅外觀",
	可编辑: "可編輯",
	"文件不是有效的主题 JSON": "檔案不是有效的主題 JSON",
	编辑布局: "編輯版面",
	打开编辑器: "開啟編輯器",
	"进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。": "進入視覺化編輯器，調整元件的顏色、背景、圓角、字號與層級；修改會立即預覽，發佈後儲存。",
	基础样式: "基礎樣式",
	窄于: "窄於",
	按当前宽度加断点: "依目前寬度加斷點",
	删除这个断点: "刪除這個斷點",
	"正在编辑窄屏覆盖，只影响该宽度以下。": "正在編輯窄螢幕覆寫，只影響該寬度以下。",
	"正在编辑这一条，只影响它自己。": "正在編輯這一條，只影響它自己。",
	横向位置: "橫向位置",
	纵向位置: "縱向位置",
	背景素材: "背景素材",
	选择图片: "選擇圖片",
	更换图片: "更換圖片",
	图片位置: "圖片位置",
	图片缩放: "圖片縮放",
	拖动九宫格选择图片显示的部分: "拖動九宮格選擇圖片顯示的部分",
	"九宫格就是实际显示的部分，拖动可直接改取景。": "九宮格就是實際顯示的部分，拖動可直接改取景。",
	模板样式: "樣式模板",
	允许溢出组件: "允許溢出元件",
	"图片过大，单张不能超过 1.5MB": "圖片過大，單張不能超過 1.5MB",
	图片读取失败: "圖片讀取失敗",
	对齐与分布: "對齊與分佈",
	右对齐: "右對齊",
	垂直居中: "垂直置中",
	底对齐: "底對齊",
	水平分布: "水平分佈",
	垂直分布: "垂直分佈",
	top: "上",
	right: "右",
	bottom: "下",
	left: "左",
	上: "上",
	右: "右",
	下: "下",
	左: "左",
	颜色样式: "顏色樣式",
	纯色: "純色",
	渐变: "漸層",
	玻璃: "玻璃",
	高透: "高透",
	低透: "低透",
	高透玻璃: "高透玻璃",
	低透玻璃: "低透玻璃",
	玻璃样式: "玻璃樣式",
	"整个区域换成现成玻璃材质，不再单独调色。": "整個區域換成現成玻璃材質，不再單獨調色。",
	适应方式: "適應方式",
	铺满: "鋪滿",
	完整显示: "完整顯示",
	平铺: "平鋪",
	拉伸: "拉伸",
	"支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。": "支援 PNG、JPEG、GIF、WebP、AVIF、SVG；動圖會照常播放。",
	实验性功能: "實驗性功能",
	实验性: "實驗性",
	"分屏文件预览（实验性）": "分屏檔案預覽（實驗性）",
	"图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。": "圖片、音視頻、PDF、Office 與 Markdown 檔案會在內建分屏裡直接開啟。功能仍在完善，遇到顯示異常可以關閉，改回預設應用程式開啟。",
	玻璃材质: "玻璃材質",
	"开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。": "開啟後整個區域變成玻璃表面，上面的顏色、漸層或圖片就是它的著色。",
	底色: "底色",
	上传图片: "上傳圖片",
	缩放: "縮放",
	请选择图片文件: "請選擇圖片檔案",
	"图片不能超过 12 MB": "圖片不能超過 12 MB",
	"图片读取失败，请换一张再试": "圖片讀取失敗，請換一張再試",
	"这张图片打不开，请换一张再试": "這張圖片打不開，請換一張再試",
	"无法处理这张图片，请换一张再试": "無法處理這張圖片，請換一張再試",
	拖动图片调整裁切位置: "拖曳圖片調整裁切位置",
	"拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。": "拖曳圖片調整位置，用滑桿縮放；圓圈內就是頭像實際顯示的部分。",
	头像大小: "頭像大小",
	圆角率: "圓角率",
	分组名称: "分組名稱",
	"删除分组 {0}": "刪除分組 {0}",
	"删除分组？": "刪除分組？",
	所属分组: "所屬分組",
	按分组筛选: "按分組篩選",
	新建分组: "新建分組",
	核心: "核心",
	移动到分组: "移動到分組",
	管理分组: "管理分組",
	"还没有分组。新建一个，把技能归类到瀑布流的各个分区。": "還沒有分組。新建一個，把技能歸類到瀑布流的各個分區。",
	"这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。": "這個分組還沒有技能。在卡片下方的分組選單裡把技能移進來。",
	重命名分组: "重新命名分組",
	按事件筛选: "按事件篩選",
	"这个事件下没有 Hook。切回「全部」看看其他事件。": "這個事件下沒有 Hook。切回「全部」看看其他事件。",
	"会话「{0}」已完成，点击打开": "會話「{0}」已完成，點擊打開",
	"会话「{0}」执行失败，点击打开": "會話「{0}」執行失敗，點擊打開",
	打开会话: "打開會話",
	桌宠: "桌寵",
	"展开其余 {0} 项": "展開其餘 {0} 項",
	部分文件不存在: "部分檔案不存在",
	"调用 {0} 次": "調用 {0} 次",
	尚未调用: "尚未調用",
	"总调用 {0} 次": "總調用 {0} 次"
}, _u = {
	交互内容: "インタラクティブコンテンツ",
	查看代码: "コードを表示",
	"交互内容运行失败，可查看代码或重试": "実行に失敗しました。コードを確認するか、再試行してください。",
	"交互内容过大，请缩小后重试": "コンテンツが大きすぎます。縮小して再試行してください。",
	"交互内容未能加载，可查看代码或重试": "読み込めませんでした。コードを確認するか、再試行してください。",
	成稿: "下書き",
	编辑成稿: "下書きを編集",
	说明: "補足",
	信息: "情報",
	提示: "ヒント",
	注意: "注意",
	警告: "警告",
	" · 依赖保留": "· 依存関係は保持されます",
	" · 待审核 {0}": "· レビュー保留中 {0}",
	" 个": " 件",
	" 个记录": "レコード",
	" 分组": "グループ化",
	" 子代理时间线": "サブエージェントのタイムライン",
	" 时间线": "タイムライン",
	" 条": " 件",
	" 的记录": "の記録",
	" 输入框": "入力ボックス",
	"# Sub-agent 委派指南\n在此编写自然语言指令，将注入到主 Agent 系统提示词中…": "# サブエージェント委任ガイド メインのエージェント システム プロンプト ワードに挿入される自然言語命令をここに記述します...",
	"# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…": "# グローバル制約は、すべてのプロジェクトに有効なディレクティブです。プロジェクト レベルの AGENTS.md がこの上にオーバーレイされます。",
	"# 输入：{0}": "# 入力: {0}",
	"# 输出：{0}": "# 出力: {0}",
	"# 项目级约束\n项目专属指令，会叠加在全局约束之上…": "# プロジェクト レベルの制約 プロジェクト固有の指示はグローバル制約に重ねられます...",
	"(项目根)": "(プロジェクトルート)",
	"* 或工具名，多个用 | 分隔": "* またはツール名。複数は | で区切られます。",
	"+ 添加节点": "+ ノードを追加",
	"+ 添加输入": "+ 入力を追加",
	"+ 添加输出": "+ 出力を追加",
	"+ 输入端口": "+入力ポート",
	"+ 输出端口": "+ 出力ポート",
	"AGENTS.md · 移动端全局规则": "AGENTS.md · モバイル グローバル ルール",
	"AGENTS.md 内容": "AGENTS.md コンテンツ",
	"AGENTS.md 已保存": "AGENTS.md が保存されました",
	"AI 创意": "AI の創造性",
	"AI 模式": "AIモード",
	"AI（兼容）": "AI(互換)",
	"API 地址": "APIアドレス",
	"API 基础 URL": "API ベース URL",
	"API 基础 URL 必须与所选供应商一致": "API ベース URL は選択したプロバイダーと一致する必要があります",
	"API 配置": "API 構成",
	"Agent 保护区域": "エージェント保護領域",
	"Agent 工具": "エージェントツール",
	"Agent 生成": "エージェントの生成",
	"Agent 锁定了这段内容": "エージェントはこのコンテンツをロックしました",
	"Core App Server 连接失败": "コア アプリ サーバーの接続に失敗しました",
	"DuckDuckGo 本地代理端口": "DuckDuckGo ローカル プロキシ ポート",
	"DuckDuckGo 本地代理端口（可选）": "DuckDuckGo ローカル プロキシ ポート (オプション)",
	"Enter 续列表 · Tab 缩进": "Enter キーを押してリストを続行します · Tab キーを押してインデントします",
	"GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。": "GPL/AGPL コンポーネントは独立したプロセスとして実行され、リポジトリにはコードが含まれません。 LamTools は、固定された JSON コントラクトに従ってのみ呼び出されます (詳細については、docs/web-search-module.md を参照してください)。",
	"HTTP 代理": "HTTP プロキシ",
	"ISO 时间": "ISO 時間",
	"JSON 文件与模板": "JSON ファイルとテンプレート",
	"Linux 直接运行本机命令，不提供 Windows shell 选择。": "Linux はネイティブ コマンドを直接実行し、Windows シェル オプションを提供しません。",
	"MCP 工具名": "MCP ツール名",
	"MCP 工具名不能为空": "MCP ツール名を空にすることはできません",
	"Markdown 笔记工作区": "マークダウン ノート ワークスペース",
	"Python 脚本": "Python スクリプト",
	"Python 脚本（兼容）": "Python スクリプト (互換性あり)",
	"Python 表达式": "Python 式",
	"RAG 不可用": "RAG は使用できません",
	"SKILL.md 正文，加载后应遵循的指引": "SKILL.md テキスト、ロード後に従うべきガイドライン",
	"Study 未启用": "スタディが有効になっていません",
	"Sub Agent 思考模式": "サブエージェントの思考モード",
	"Sub Agent 模型": "サブエージェントモデル",
	"Sunday 工作区": "日曜日のワークスペース",
	"Sunday 设置": "日曜日の設定",
	"URL 不能为空": "URL を空にすることはできません",
	"Web Search 引擎": "ウェブ検索エンジン",
	"[…截断，仅显示尾部…]\n": "[...切り詰められ、尾部のみが表示されています...]",
	"^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$": "^サブエージェント\\s+(.+?)\\s+({0})\\s*[::]\\s*([\\s\\S]+)$",
	"^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$": "^サブエージェント\\s+(.+?)\\s+({0})\\s*。 ?\\s*$",
	"at（ISO 时间）": "(ISO 時間)",
	"baidu（百度，国内可达）": "baidu (Baidu、中国でアクセス可能)",
	"bing（必应中文）": "bing (Bing 中国語)",
	"command (Shell 命令)": "コマンド (シェルコマンド)",
	"command 不能为空": "コマンドを空にすることはできません",
	"ddg（DuckDuckGo，海外）": "ddg (DuckDuckGo、海外)",
	"hook 失败时阻断执行": "フックが失敗した場合に実行をブロックする",
	"hooks.json 内容": "hooks.jsonコンテンツ",
	"hooks.json 当前无法解析（不是合法 JSON），已取消保存。请先到「原始配置」视图修复后再添加 Hook。": "hooks.json は現在解析できず (正当な JSON ではない)、キャンセルされました。 「元の構成」ビューに移動して修復し、フックを追加してください。",
	"http (HTTP 请求)": "http (HTTP リクエスト)",
	"load_context.jsonc · 移动端全局加载规则": "load_context.jsonc · モバイル端末のグローバル読み込みルール",
	"mcp (MCP 工具)": "mcp (MCP ツール)",
	"prompt (内联提示)": "プロンプト (インラインプロンプト)",
	"websearch.jsonc 内容": "websearch.jsonc コンテンツ",
	"y = x * 2（输入端口名当变量，给输出端口名赋值）": "y = x * 2 (入力ポート名を変数として使用し、値を出力ポート名に割り当てます)",
	"{0} {1}": "{0} {1}",
	"{0} {1} {2}": "{0} {1} {2}",
	"{0} {1} 失败{2}": "{0} {1} が失敗しました {2}",
	"{0} {1} 详情": "{0} {1} の詳細",
	"{0} {1}{2}": "{0} {1}{2}",
	"{0} · 文件保留": "{0} · ファイルの保持",
	"{0} · 项目设置": "{0} · プロジェクト設定",
	"{0} › {1}编辑 {2}": "{0} › {1}編集 {2}",
	"{0} › 编辑 {1}": "{0} › {1} を編集",
	"{0} 个工具": "{0} ツール",
	"{0} 个文件": "{0} ファイル",
	"{0} 个文件 · {1}": "{0} ファイル · {1}",
	"{0} 个进程 · {1} 个运行中": "{0} プロセス · {1} が実行中",
	"{0} 会话操作": "{0} セッション操作",
	"{0} 分段": "{0} セグメント",
	"{0} 分钟前": "{0}分前",
	"{0} 天前": "{0}日前",
	"{0} 学习进度 {1}%": "{0} 学習の進行状況 {1}%",
	"{0} 小时前": "{0}時間前",
	"{0} 开关": "{0} の切り替え",
	"{0} 成果操作": "{0} 結果操作",
	"{0} 文本预览": "{0} テキスト プレビュー",
	"{0} 文档": "{0} ドキュメント",
	"{0} 次调用": "{0} 回の呼び出し",
	"{0} 段": "{0} セグメント",
	"{0} 的操作": "{0} の操作",
	"{0} 的格式工具": "{0} の書式設定ツール",
	"{0} 的过程": "{0}のプロセス",
	"{0} 秒": "{0} 秒",
	"{0} 至 {1}": "{0} から {1}",
	"{0} 行": "{0} 行",
	"{0} 详情": "{0} の詳細",
	"{0} 附件操作": "{0} アタッチメント操作",
	"{0} 项 · 文件保留": "{0} 個のアイテム · ファイルが保持されました",
	"{0} 项目操作": "{0} プロジェクトの操作",
	"{0}/.lam/config/subagent/settings.json": "{0}/.lam/config/subagent/settings.json",
	"{0}/{1} 在线": "{0}/{1} オンライン",
	"{0}s 后重试：{1}": "{0} 秒後に再試行: {1}",
	"{0}{1}": "{0}{1}",
	"{0}关闭 {1}": "{0} オフ {1}",
	"{0}内容": "{0} コンテンツ",
	"{0}分": "{0} ポイント",
	"{0}原上下文已保留": "{0}元のコンテキストが保持されています",
	"{0}向 {1} 发送消息": "{0} が {1} にメッセージを送信しました",
	"{0}天": "{0} 日",
	"{0}小时": "{0}時間",
	"{0}必须是正数": "{0} は正の数である必要があります",
	"{0}接收 {1} 的消息": "{0} が {1} からメッセージを受信しました",
	"{0}操作": "{0} オペレーション",
	"{0}月{1}日": "{0}月{1}日",
	"{0}标题": "{0} タイトル",
	"{0}说明": "{0} 説明",
	"{0}运行详情": "{0} 操作の詳細",
	"{0}颜色节点": "{0} カラーノード",
	"{0}（{1}–{2}）": "{0} ({1}–{2})",
	"{0}（当前配置）": "{0} (現在の構成)",
	"{0}，不可点击": "{0}、クリックできません",
	"{0}，打开子代理面板": "{0}、サブエージェント パネルを開きます",
	"· 优先级": "· 優先度",
	"· 历史": "· 履歴",
	"· 对话": "· ダイアログ",
	"· 将自动添加模板内模型": "· テンプレート内モデルは自動的に追加されます",
	"· 已登录": "· ログインしました",
	"· 来源：": "· ソース:",
	"· 运行": "· 実行",
	通过: "合格",
	"。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 上下文」内编辑。": "。注入順序: 最初にグローバル制約 (.lam/core/config/AGENTS.md)、次にこのファイルを追加し、その 2 つを追加します。グローバル制約は「設定 → コンテキスト」で編集します。",
	"「{0}」文件夹里的方案 — 点开读全文，就绪后开工。": "「{0}」フォルダー内の計画 - クリックして全文を読み、準備ができたら作業を開始します。",
	"」将被删除": "\"削除されます\"",
	"」将被删除，且无法恢复。": "\" は削除されるため、復元できません。",
	"」文件夹里的方案 — 点开读全文，就绪后开工。": "「フォルダー内の計画 - クリックして全文を読み、準備ができたら作業を開始します。",
	"」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。": "\"フォルダー。書き込み後、ここに表示されます。プランは通常の Markdown ドキュメントですが、新しく作成して書き込むこともできます。",
	"」还有没保存的内容，离开就会丢掉。": "「未保存のコンテンツがあり、終了すると失われます。」",
	"一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。": "ステップはモデルの応答とその後のツールの結果です。 0 ステップはデフォルトで保持され、履歴が要約されます。その後、プログラムは、最新 20 件のユーザー指示の元のテキストを番号付きの「最近のユーザー メッセージ」段落として追加します。トークンのバジェットが不十分な場合、古いエントリは警告なしに破棄されます。",
	"一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务， 你的数据与配置都留在本机。": "ローカルファーストのエージェント ワークベンチ: データと構成をローカルに保ちながら、セッション、メモリ、自動タスクを管理します。",
	一句话说明这个技能的用途: "このスキルの目的を一文で説明してください",
	一次性: "使い捨て",
	"一次性触发器需要 at 时间": "ワンタイムトリガーには一度に必要があります",
	上一步: "前のステップ",
	上一页附件: "前のページの添付ファイル",
	上下文: "コンテキスト",
	"上下文 {0}（{1}）": "コンテキスト {0} ({1})",
	"上下文、输出、Temperature 与高级适配": "コンテキスト、出力、温度、および高度な適応",
	上下文占用: "コンテキストが占有されています",
	上下文压缩: "コンテキスト圧縮",
	上下文已压缩: "コンテキストが圧縮されました",
	上下文窗口: "コンテキストウィンドウ",
	上下文菜单: "コンテキストメニュー",
	"上传中…": "アップロード中...",
	上传失败: "アップロードに失敗しました",
	"上传失败 {0} 个 — {1}": "アップロードに失敗しました {0} — {1}",
	上传文件: "ファイルをアップロードします",
	"上传文件，或让助手把要留存的产出归入资料库。": "ファイルをアップロードするか、アシスタントに出力をライブラリに保存させます。",
	上移: "上に移動",
	"上移 {0}": "{0} 上に移動",
	上级目录: "親ディレクトリ",
	上页: "前のページ",
	下一个模式: "次のモード",
	下一页附件: "次のページの添付ファイル",
	下次: "次回",
	下移: "下に移動",
	"下移 {0}": "{0} の下に移動します",
	"下载 {0}%": "ダウンロード {0}%",
	下载中: "ダウンロード中",
	"下载中…": "ダウンロード中...",
	下载安装包: "インストールパッケージをダウンロードする",
	"下载完成 100%": "ダウンロードが 100% 完了しました",
	"下载完成后点击「立即安装」。": "ダウンロード後、「今すぐインストール」をクリックします。",
	"下载完成后请先退出 Sunday，再运行安装包完成升级。": "ダウンロード後、アップグレードを完了するためにインストール パッケージを実行する前に日曜日を終了してください。",
	下页: "次のページ",
	不使用代理的地址: "プロキシなしのアドレス",
	不可用: "利用できません",
	不归档: "アーカイブされていません",
	不迭代: "反復していません",
	不限: "制限なし",
	"与运行时的确认通道已断开，恢复连接后才能提交选择。": "ランタイムへの確認チャネルが切断されており、接続が復元されるまで選択を送信できません。",
	个: "個人的な",
	"个 · 工作流 revision": "個別・ワークフロー改訂",
	个产物: "製品",
	个人: "個人用",
	个文件: "ファイル",
	个条目: "アイテム",
	个模型: "モデル",
	"个模型，可来自多个供应商": "モデルは複数のベンダーからのものである可能性があります",
	个节点: "ノード",
	中: "中",
	"中止（默认）": "中止 (デフォルト)",
	中继: "リレー",
	"中继.{0}": "リレー。{0}",
	中继点: "中継ポイント",
	中间产物: "中間生成物",
	"中（默认）": "中 (デフォルト)",
	"为 {0} 添加第一个模型": "{0} の最初のモデルを追加しています",
	"为不同工作模式配置模型可用的工具。": "さまざまな作業モードのモデルを構成するために使用できるツール。",
	"为供应商添加一个可调用的模型。": "サプライヤー用の呼び出し可能モデルを追加します。",
	主导航: "メインナビゲーション",
	主界面: "メインインターフェイス",
	主题: "テーマ",
	"主题会即时同步到当前 Sunday 界面。": "テーマは現在の日曜日のインターフェースに即座に同期されます。",
	"主题和密度只影响当前 Sunday 界面。": "テーマと密度は、現在の日曜日のインターフェイスにのみ影響します。",
	主题预设: "テーマのプリセット",
	"之后可在 Sunday 设置中继续添加供应商、模型或调整权限模式。": "後からサプライヤー、モデルを追加したり、日曜日の設定で権限モードを調整したりすることができます。",
	事件: "イベント",
	"事件 · {0}": "イベント · {0}",
	"事件审计（": "イベント監査 (",
	事件类型: "イベントの種類",
	"事件类型，如 artifact.changed": "イベント タイプ (artifact.changed など)",
	"事件触发器需要 event_type": "イベントトリガーにはevent_typeが必要です",
	于: "で",
	产品发布: "製品リリース",
	产物: "製品",
	人工任务: "ヒューマンタスク",
	人工任务已提交: "ヒューマンタスクが送信されました",
	人工协作: "人間のコラボレーション",
	人工审批: "承認",
	"仅在需要时暴露给 Agent": "必要な場合にのみエージェントに公開される",
	"仅展示用户、中间产物与产物三类。移除只改变成果库状态，不删除文件。": "ユーザー、中間製品、製品の 3 つのカテゴリのみが表示されます。削除すると、結果ライブラリのステータスが変更されるだけで、ファイルは削除されません。",
	"仅支持 .zip 安装包：{0}": ".zip インストール パッケージのみがサポートされています: {0}",
	仅用于建立设备信任: "デバイスの信頼を確立するためにのみ使用されます",
	从一个新会话开始: "新しいセッションから開始する",
	"从左侧文件树打开一篇笔记。": "左側のファイル ツリーからメモを開きます。",
	"从左侧添加一个模型供应商，开始使用 Sunday。": "日曜日の使用を開始するには、左側からモデル プロバイダーを追加します。",
	从当前环境导入: "現在の環境からインポート",
	从成果库移除: "結果ライブラリから削除",
	"从成果库移除 (": "リポジトリから削除されました (",
	"从成果库移除 {0}": "成果ライブラリから {0} を削除",
	"从成果库移除？": "結果ライブラリから削除しますか?",
	从收藏移除: "お気に入りから削除",
	从此处另开会话: "ここから新しいセッションを開きます",
	从此节点运行: "このノードから実行します",
	"从此节点运行…": "このノードから実行中...",
	"从第 {0} 行": "行 {0} から",
	从设备文件中选择: "デバイスファイルから選択",
	从资料库移除: "ライブラリから削除",
	代码: "コード",
	代码开发: "コード開発",
	任务: "タスク",
	"任务 {0}…": "タスク {0}...",
	"任务创建后，这里会显示每次运行的时间与结果。": "タスクが作成されると、各実行の時間と結果がここに表示されます。",
	任务已处理: "タスクが処理されました",
	任务数量: "タスクの数",
	任务标题: "タスクのタイトル",
	任务类型: "タスクの種類",
	"任务类型 {0}": "タスクタイプ {0}",
	"任务类型“{0}”重复，请保留一条。": "タスク タイプ \"{0}\" が重複しています。1 つを保持してください。",
	"任务运行中，请先停止任务再分叉": "タスクは実行中です。フォークする前にタスクを停止してください。",
	"任务运行中，请先停止任务再回退": "タスクは実行中です。まずタスクを停止してからロールバックしてください。",
	"任务运行中，请先停止任务再编辑": "タスクは実行中です。編集する前にタスクを停止してください。",
	任务页签: "タスクタブ",
	份方案: "計画",
	优先级: "優先度",
	"优先级 {0}": "優先度 {0}",
	会参与激活: "アクティベーションに参加します",
	会话: "セッション",
	会话与项目: "セッションとプロジェクト",
	会话已重命名: "セッションの名前が変更されました",
	会话操作: "セッション操作",
	会话标题: "セッションタイトル",
	估算: "推定",
	位置: "場所",
	低: "低",
	余烬渐变: "エンバーグラデーション",
	作为引导发送: "ブートとして送信されました",
	"使用官方模板自动填充连接信息和模型。": "公式テンプレートを使用して、接続情報とモデルを自動的に入力します。",
	"使用选定模型生成结果。": "選択したモデルを使用して結果を生成します。",
	"使用默认应用打开？": "デフォルトのアプリで開きますか?",
	"例如 C:\\certs\\root-ca.pem": "例: C:\\certs\\root-ca.pem",
	"例如 deepseek-v4-flash": "例:ディープシーク-v4-フラッシュ",
	"例如 http://127.0.0.1:7890": "例: http://127.0.0.1:7890",
	"例如 localhost,127.0.0.1,::1,.example.com,*.corp.com": "たとえば、localhost,127.0.0.1,::1,.example.com,*.corp.com",
	"例如：Free": "例: 無料",
	"例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议": "例: 過去 24 時間の送信内容を確認し、考えられるバグと修復の提案を要約します。",
	"例如：invoice.created": "例: invoice.created",
	"例如：quality >= 0.8": "例: 品質 >= 0.8",
	"例如：代码审查": "例: コードレビュー",
	"例如：偏好": "例: 設定",
	"例如：导出显示进度": "例: エクスポートで進行状況が表示される",
	"例如：我的供应商": "例: 私のサプライヤー",
	"例如：手机项目": "例: 携帯電話プロジェクト",
	"例如：每日同步": "例: 毎日の同期",
	"例如：用户偏好.md": "例: UserPreferences.md",
	"例如：迭代计划": "例: 反復計画",
	供应商: "プロバイダー",
	供应商列表: "サプライヤーリスト",
	供应商名称: "サプライヤー名",
	供应商已删除: "サプライヤーが削除されました",
	供应商已更新: "サプライヤーが更新されました",
	供应商已添加: "サプライヤーが追加されました",
	供应商空状态: "サプライヤー空ステータス",
	供应商详情: "サプライヤーの詳細",
	供应商配置: "サプライヤー構成",
	依赖: "依存関係",
	依赖就绪: "依存関係の準備ができました",
	依赖未知: "不明な依存関係",
	依赖缺失: "依存関係がありません",
	侧栏滚动条: "サイドバーのスクロールバー",
	拖动调整左侧栏宽度: "ドラッグして左側の列の幅を調整します",
	便签: "メモ",
	"便签.{0}": "注意。{0}",
	保存: "保存",
	保存中: "保存中",
	"保存中…": "保存中...",
	"保存为所有项目的全局基线；项目可单独覆盖。": "すべてのプロジェクトのグローバル ベースラインとして保存されました。プロジェクトは個別にオーバーライドできます。",
	保存供应商: "サプライヤーを保存",
	"保存冲突，请选择处理方式": "競合を保存しています。処理方法を選択してください",
	"保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。": "保存の競合: リモート バージョンが更新されました。リモートのものを使用するか、ローカルに保持して再試行するかを選択してください。",
	保存到: "保存先",
	"保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global": "グローバル構成 ~/.lam/core/config/subagent/guide.md に保存します。プロジェクトレベルの構成は、プロジェクト設定内で編集する必要があります。空白のままにして保存すると、組み込みのデフォルトに復元されます。 CLI: コア サブエージェント ガイド show/set/edit --scope global",
	"保存到项目配置 {0}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>": "プロジェクト構成 {0}/.lam/config/subagent/guide.md に保存しています。空白として保存すると、プロジェクト レベルの構成が削除され、継承されたグローバル/組み込みのデフォルトに戻ります。 CLI: コア サブエージェント ガイド show/set/edit --scope project --work-root <root>",
	"保存到项目配置 {0}/.lam/config/subagent/settings.json。": "プロジェクト構成 {0}/.lam/config/subagent/settings.json に保存します。",
	"保存后将移除当前项目覆盖，恢复继承全局策略。": "保存後、現在のプロジェクトの上書きが削除され、グローバル ポリシーの継承が復元されます。",
	"保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。": "保存後に新しく開始されたモデル、MCP、およびコマンド呼び出しは、新しい設定にすぐに従います。接続されている MCP サービスと実行中のバックグラウンド コマンドを再起動する必要があります。",
	"保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "このデバイスのアプリのプライベート SQLite 構成に保存されました。 「プロジェクト設定 → プロジェクト」でプロジェクト レベルのルールを編集してください。この 2 つはシステム プロンプト ワードを挿入するために一緒に追加されます。",
	"保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。": "このデバイスのアプリプライベート SQLite 構成に保存されたグローバル ルールは、ローカル ワークスペースにオーバーレイされます。",
	"保存失败，修改仍保留在当前编辑器。": "保存に失敗しました。変更は現在のエディタに残っています。",
	"保存失败：{0}": "保存に失敗しました: {0}",
	"保存失败：{0}。你的草稿仍保留，请核对重合区域。": "保存に失敗しました: {0}。下書きはまだ残っています。重なっている部分を確認してください。",
	"保存失败：笔记已被更新，你的草稿仍保留。": "保存に失敗しました: メモは更新されましたが、下書きは残ります。",
	保存工作流: "ワークフローの保存",
	"保存工作流（有未保存修改）": "ワークフローの保存 (未保存の変更あり)",
	保存并切换: "保存して切り替える",
	保存并继续: "保存して続行",
	保存成员: "メンバーの保存",
	保存模型: "モデルの保存",
	保存触发器: "トリガーの保存",
	保存配置: "構成の保存",
	保持电脑运行: "コンピューターを実行し続けます",
	"保留最近的 Step": "最新のステップを保持します",
	保留本地修改并用远端版本号重试保存: "ローカルの変更を保持し、リモートのバージョン番号を使用して再度保存してください",
	保留本地并重试: "ローカルを維持して再試行してください",
	信任: "信頼",
	修改于: "から変更されました",
	"修改后需重启后端生效。": "変更を有効にするには、バックエンドを再起動する必要があります。",
	"修改范围：原 {0} 行起，新 {1} 行起": "変更範囲: 元の {0} 行から始まり、新しい {1} 行から始まります",
	候选结论: "結論候補",
	值: "値",
	"停止失败：{0}": "停止に失敗しました: {0}",
	停止工作流: "ワークフローを停止します",
	停止运行: "実行を停止しました",
	"停止运行（子代理仍在运行）": "停止しました (サブエージェントはまだ実行中です)",
	停用: "無効にする",
	"停用失败：{0}": "非アクティブ化に失敗しました: {0}",
	允许工作目录外: "作業ディレクトリ外を許可します",
	允许手机控制这台电脑: "電話によるこのコンピュータの制御を許可します",
	允许访问工作目录以外: "作業ディレクトリ外のアクセスを許可する",
	"允许读写工作目录之外的路径。": "作業ディレクトリ外のパスの読み取りと書き込みを許可します。",
	先保存工作流再排队: "キューに入れる前にワークフローを保存します",
	先保存工作流再运行: "ワークフローを実行する前に保存してください",
	先在左侧选择一个项目: "最初に左側の項目を選択してください",
	"先在左侧选择一个项目 — 资料库跟随项目。": "最初に左側でプロジェクトを選択します。ライブラリはプロジェクトに従います。",
	"先在左侧选择一个项目 — 资料库跟随项目文件夹。": "左側でプロジェクトを選択することから始めます。ライブラリはプロジェクト フォルダーに従います。",
	"先提供背景方向，其他区域可继续单独调整。": "最初に背景の方向を指定し、他の領域を個別に調整し続けることができます。",
	"先用 read_file 读回这份方案（它在当前项目之外，读到它需要你先申请访问批准），对照仓库现状核对需求与步骤，有出入的地方先记下结论；": "まず、read_file を使用して計画を読み返し (計画は現在のプロジェクトの外にあり、読むには最初にアクセス承認を申請する必要があります)、倉庫の現在の状況に照らして要件と手順を確認し、矛盾がある場合は結論を書き留めます。",
	"先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；": "まず、read_file を使用して計画を読み返し、倉庫の現在の状況に照らして要件と手順を確認し、矛盾がある場合は結論を書き留めて計画ファイルを更新します。",
	先进入一个项目: "最初にプロジェクトを入力してください",
	"先进入一个项目，再操作它的记忆": "最初にプロジェクトを入力してから、そのメモリを操作します",
	先选一个工作目录: "最初に作業ディレクトリを選択してください",
	"克制的中性灰阶。": "抑制されたニュートラル グレースケール。",
	"全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。": "グローバル コンテキスト。注入順序: グローバル AGENTS.md (優先順位 5) → プロジェクト AGENTS.md (10)。 load_context の追加/除外は各ワークスペースにグローバルに重畳されます。",
	全局上下文加载: "グローバル コンテキストの読み込み",
	"全局基线适用于所有项目；项目可按同名任务类型覆盖。": "グローバル ベースラインはすべてのプロジェクトに適用されます。プロジェクトは、同じ名前のタスク タイプによって上書きできます。",
	"全局搜索：跨项目查找会话、消息与学习资料。": "グローバル検索: プロジェクト全体で会話、メッセージ、学習教材を検索します。",
	全局约束: "グローバル制約",
	"全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 {0} 条。": "グローバル ルールがベースラインとして使用されます。ここではプロジェクト カバレッジのみが編集され、同じ名前のタスク タイプはプロジェクト ルールの対象となります。現在、{0} 個のアイテムが結合されています。",
	全局记忆: "グローバルメモリ",
	"全应用的出口流量走哪里，以及它们信任哪个根证书。": "すべてのアプリケーションの出力トラフィックはどこに送信され、どのルート証明書が信頼されるのか。",
	全选: "すべて選択",
	全部: "すべて",
	全部删除: "すべて削除",
	全部工具: "すべてのツール",
	全部工具可用: "すべてのツールが利用可能",
	全部状态: "すべてのステータス",
	全部类型: "すべてのタイプ",
	全部角色: "すべての文字",
	公式: "数式",
	"六位数字码 5 分钟内有效且只能使用一次": "6 桁のコードは 5 分以内に有効で、1 回のみ使用できます",
	"共 {0} 个 · 已信任 {1}{2}": "合計 {0} 件 · 信頼済み {1}{2}",
	"共 {0} 个 · 已启用 {1}": "合計 {0} · {1} が有効になりました",
	关于与更新: "このアプリと更新",
	关系: "関係",
	关系图: "関係図",
	关系图例: "関係の凡例",
	关系图加载中: "関係図の読み込み",
	关联: "関連付け",
	关闭: "閉じる",
	关闭并保留草稿: "下書きを残して閉じる",
	"恢复默认？": "デフォルトに戻しますか？",
	"将清除已发布的主题与当前草稿，无法撤销。": "公開済みテーマと現在の下書きが消去されます。元に戻せません。",
	"主题文件过大，请检查是否误选了其他文件": "テーマファイルが大きすぎます。ファイルを確認してください",
	"关闭 Sub Agent": "サブエージェントを閉じる",
	"关闭 {0} 失败": "{0}を閉じることができませんでした",
	"关闭了 {0}": "{0}は閉じられています",
	"关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。": "ツールは、閉じた後にツールセットから削除されます。有効になっているが API アドレスが空の場合、呼び出しは「未構成のグラフ API」を返します。",
	关闭工作流标签: "ワークフローラベルを閉じる",
	"关闭提示：{0}": "プロンプトを閉じる: {0}",
	关闭文本预览: "テキスト プレビューをオフにする",
	关闭网格吸附: "グリッド スナップをオフにする",
	关闭节点目录: "ノードディレクトリを閉じます",
	"关闭设置？": "設定を閉じますか?",
	关闭详情: "詳細を閉じる",
	关闭详细调整: "詳細調整をオフにする",
	关闭配对码: "ペアリング コードをオフにする",
	关闭面板: "パネルを閉じる",
	关闭预览: "プレビューを閉じる",
	其他: "その他",
	其他处理方式: "他の処理方法",
	"其余时间用另一个模式；跨天时段同样有效。": "残りの時間は別のモードを使用してください。日をまたぐ期間も有効です。",
	兼容: "互換性あり",
	"兼容旧版 AI 节点。": "古いバージョンの AI ノードと互換性があります。",
	"兼容旧版 Python 脚本节点。": "Python スクリプト ノードの古いバージョンと互換性があります。",
	"兼容旧版分支节点。": "古いバージョンのブランチ ノードと互換性があります。",
	"兼容旧版转换节点。": "従来の変換ノードと互換性があります。",
	内存中断自动续跑: "メモリ中断後に実行を自動的に再開する",
	内容宽度: "コンテンツの幅",
	"内容（content）": "コンテンツ",
	内核配置: "カーネル構成",
	内置: "内蔵",
	内置默认: "組み込みのデフォルト",
	"内置：": "組み込み:",
	写: "書き込み",
	"写下想法…": "アイデアを書き留めてください...",
	"写下注释…": "メモを書きます...",
	"写点什么，助手下次就会读到它。": "何かを書くと、アシスタントが次回それを読み上げます。",
	"决定工具执行前是否需要你确认。": "ツールが実行前に確認を必要とするかどうかを判断します。",
	"决定模型是否接收图片，以及是否启用推理参数。": "モデルが画像を受信するかどうか、および推論パラメーターが有効かどうかを決定します。",
	"准备开干！": "開始する準備ができました。",
	几号: "番号は何ですか?",
	出错: "エラー",
	分层: "レイヤ化",
	"分支 {0}": "ブランチ {0}",
	"分支（兼容）": "ブランチ (互換)",
	分段: "セグメンテーション",
	分组: "グループ化",
	"分组.{0}": "グループ化。{0}",
	分组键: "グループ化キー",
	切换侧栏: "サイドバーの切り替え",
	"切换到 ": "に切り替える",
	"切换前要如何处理当前草稿？": "切り替える前に現在のドラフトを処理するにはどうすればよいですか?",
	切换右侧栏: "右の列を切り替えます",
	切换模式: "モードの切り替え",
	"切换模式，当前 {0}": "モードを切り替え（現在：{0}）",
	"列出 {0}": "リスト {0}",
	列出目录: "ディレクトリのリスト",
	列表视图: "リストビュー",
	刚刚: "たった今",
	刚刚打开: "開いたばかりです",
	创建: "作成",
	"创建 {0}": "{0} を作成します",
	"创建一个模型组来整理所有供应商下的模型。": "モデル グループを作成して、すべてのサプライヤーの下でモデルを編成します。",
	创建中: "作成中",
	"创建中…": "作成中...",
	创建了: "作成されました",
	创建你的第一个文件夹: "最初のフォルダーを作成します",
	创建分组来整理常用模型: "グループを作成して一般的に使用されるモデルを整理する",
	"创建失败：{0}": "作成に失敗しました: {0}",
	创建定时任务: "スケジュールされたタスクを作成する",
	创建技能: "スキルの作成",
	创建文件: "ファイルの作成",
	创建文件夹: "フォルダーの作成",
	"创建文件夹，整理资料库中的方案。": "フォルダーを作成し、ライブラリ内にソリューションを整理します。",
	创建项目: "プロジェクトの作成",
	删: "削除",
	删除: "削除",
	"删除 ": "削除",
	"删除 Hook？": "フックを削除しますか?",
	"删除 {0}": "{0}を削除します",
	"删除 {0} 行": "行 {0} を削除します",
	"删除会话及历史？": "セッションと履歴を削除しますか?",
	"删除供应商及其模型配置？": "サプライヤーとそのモデル構成を削除しますか?",
	删除全部队列项和历史: "すべてのキュー項目と履歴を削除します",
	删除内容: "コンテンツの削除",
	"删除子代理 ": "サブエージェントの削除",
	删除容器及其内容: "コンテナとそのコンテンツを削除します",
	删除已结束历史: "終了した履歴を削除します",
	删除待发送内容: "送信するコンテンツを削除します",
	"删除技能 {0}": "スキル {0} を削除します",
	"删除技能及目录？": "スキルとディレクトリを削除しますか?",
	删除文件夹: "フォルダーを削除します",
	"删除文件夹（含里面全部条目）": "フォルダーを削除します (フォルダー内のすべてのエントリを含む)",
	删除方案: "プランの削除",
	删除标记: "マークを削除",
	"删除模型组（模型保留）？": "モデル グループを削除します (モデルは保持されます)?",
	"删除模型配置？": "モデル構成を削除しますか?",
	删除此消息及之后内容: "このメッセージと後続のコンテンツを削除します",
	删除此轮及之后内容: "このラウンドとそれ以降のコンテンツを削除します",
	删除组: "グループの削除",
	"删除角色分配 {0}": "ロール割り当て {0} を削除します",
	删除记忆: "メモリの削除",
	删除连线: "接続を削除します",
	"删除选中元素（{0}）": "選択した要素 ({0}) を削除します",
	删除项目: "プロジェクトを削除します",
	"删除项目及会话记录？": "プロジェクトとセッションのレコードを削除しますか?",
	刷新: "更新",
	"刷新中…": "リフレッシュしています...",
	刷新人工任务: "ヒューマンタスクを更新します",
	刷新成果库: "結果ライブラリを更新します",
	刷新激活状态: "アクティブ化ステータスの更新",
	刷新笔记文件树: "メモ ファイル ツリーを更新します",
	刷新进程列表: "プロセスリストを更新します",
	刷新队列: "キューを更新します",
	前置: "プレフィックス",
	剪切: "カット",
	加入队列: "キューに参加します",
	加粗: "太字",
	"加载 {0} 失败：{1}": "{0} のロードに失敗しました: {1}",
	加载中: "読み込み中",
	"加载中...": "読み込み中...",
	"加载中…": "読み込み中...",
	"加载失败：": "読み込みに失敗しました:",
	"加载失败：{0}": "読み込みに失敗しました: {0}",
	加载技能: "スキルをロードしています",
	"加载技能 · {0}": "スキルを読み込み中 · {0}",
	加载类型: "読み込みタイプ",
	助手回复: "アシスタントの応答",
	勾选后从成果库移除: "チェック後に結果ライブラリから削除します",
	匹配器: "マッチャー",
	"匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。": "これらのホストに一致するリクエストは、HTTP プロキシを経由せずに直接接続されます。コマンド ツールは、同じルールに従って NO_PROXY を書き込みます。複数のルールはカンマで区切られます。",
	单次: "シングル",
	"单次 (single)": "シングル",
	"单次 · {0}": "シングル · {0}",
	单步调试: "シングルステップのデバッグ",
	"单步运行中…": "シングルステップ...",
	卸载: "アンインストール",
	"卸载插件及目录？": "プラグインとディレクトリをアンインストールしますか?",
	历史: "履歴",
	"压缩保留最近 Step 数": "圧縮では最新のステップ番号が保持されます",
	压缩后: "圧縮後",
	压缩未完成: "圧縮が完了していません",
	原上下文已保留: "元のコンテキストが保持されています",
	"原上下文已保留 · {0}": "元のコンテキストが保持されています · {0}",
	原始配置: "元の構成",
	"原文已变化或暂未加载，无法准确定位。": "元のテキストが変更されているか、まだロードされていないため、正確に見つけることができません。",
	"原模型「{0}」已不可用，已改用「{1}」": "元のモデル \"{0}\" は使用できなくなったため、\"{1}\" に置き換えられました",
	去登录: "ログインに移動",
	参数: "パラメータ",
	双击打开: "ダブルクリックして開きます",
	双击文本预览: "テキストプレビューをダブルクリックします",
	"发现新版本 v": "新しいバージョン v が見つかりました",
	"发现新版本 v{0}": "新しいバージョン v{0} が見つかりました",
	"发现新版本 v{0}，点击下载": "新しいバージョン v{0} が見つかりました。クリックしてダウンロードしてください",
	"发现新版本 v{0}，点击打开下载页": "新しいバージョン v{0} が見つかりました。クリックしてダウンロード ページを開きます",
	发现新版本时会在顶部显示提示条: "新しいバージョンが見つかったときに上部にツールチップを表示します",
	发送: "送信",
	取消: "キャンセル",
	取消下载: "ダウンロードをキャンセルします",
	取消任务: "タスクをキャンセルします",
	取消固定右侧栏: "右サイドバーの固定を解除する",
	取消固定左侧栏: "左側の列の固定を解除します",
	"取消失败：{0}": "キャンセルに失敗しました: {0}",
	取消收藏: "お気に入りをキャンセルする",
	"取消收藏：{0}": "コレクションをキャンセル: {0}",
	"取消暴露为 Agent 工具": "エージェントとして非公開ツール",
	取消更新: "更新をキャンセルします",
	取消置顶: "ピン留めを解除",
	"取消运行 {0}": "{0} の実行をキャンセルします",
	"取消选择 {0}": "{0}の選択を解除します",
	"只属于「{0}」的记忆 — 模型在会话里读它，你在这里整理它。": "\"{0}\" のみに属するメモリ — モデルはセッションでメモリを読み取り、ここで整理します。",
	"只改变背景板，聊天区、输入栏和控件保持中性。": "背景パネルのみが変更され、チャット領域、入力フィールド、およびコントロールはニュートラルのままです。",
	可用模式: "利用可能なモード",
	可用至: "利用可能",
	"可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。": "オプション。 PEM ルート証明書パスを入力した後、モデルはそれを信頼のルートとして要求し、SSL_CERT_FILE や NODE_EXTRA_CA_CERTS などの変数を MCP およびコマンド ツールに挿入します。空白のままにすると、システムの信頼チェーンが使用されます。",
	"可选：自然语言格式说明": "オプション: 自然言語形式の説明",
	右侧工具: "右側のツール",
	右侧工具栏: "右ツールバー",
	合并: "マージ",
	"合并多个输入，取首个有效值。": "複数の入力を結合し、最初の有効な値を取得します。",
	"同一主题在两种模式下保持不同的明暗气质。": "同じテーマが 2 つのモードで異なる明暗の品質を維持します。",
	同步项目: "プロジェクトの同期",
	名称: "名前",
	名称不能包含路径分隔符: "名前にパス区切り文字を含めることはできません",
	"后端进程已停止响应（可能已崩溃）。请重启应用以恢复。": "バックエンド プロセスが応答を停止しました (クラッシュした可能性があります)。回復するにはアプリを再起動してください。",
	"向 Sub Agent 发送消息...": "サブエージェントにメッセージを送信します...",
	"向 {0} 发送了消息": "メッセージを {0} に送信しました",
	"向 {0} 发送消息失败": "{0} へのメッセージの送信に失敗しました",
	向下调整高度: "高さを下方向に調整します",
	"向供应商 API 发送的模型标识。": "モデル ID がベンダー API に送信されました。",
	向右调整宽度: "幅を右に調整",
	启动时自动检查更新: "起動時にアップデートを自動的に確認します",
	启用: "有効にする",
	"启用 generate_image 工具": "画像生成ツールを有効にする",
	启用了: "有効",
	"启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。": "generate_image ツールは、有効になった後にのみツール セットをアップロードします。有効になっていない場合、通話は傍受されます。",
	启用或关闭生图工具: "描画ツールを有効または無効にします",
	"启用技能 {0}": "スキル {0} を有効にします",
	启用推理预算: "推論バジェットを有効にする",
	"启用插件 {0}": "プラグイン {0} を有効にする",
	命中: "ヒットしました",
	命令: "コマンド",
	"命令 ": "コマンド",
	"命令 {0}": "コマンド {0}",
	"命令…（curl/git/ffmpeg 等）": "コマンド... (curl/git/ffmpeg など)",
	命令行: "コマンドライン",
	命令输出: "コマンド出力",
	回到子代理最新: "サブエージェントの最新の状態に戻る",
	回到最新: "最新に戻る",
	回到最新消息: "最新ニュースに戻る",
	回到编辑: "編集に戻る",
	回滚: "ロールバック",
	"固定 revision": "修正されたリビジョン",
	固定右侧栏: "右サイドバーを修正",
	固定左侧栏: "左列を修正",
	图标: "アイコン",
	图标色彩: "アイコンの色",
	图片: "画像",
	"图片加载失败：{0}": "画像の読み込みに失敗しました: {0}",
	"图片暂时取不到，重试": "画像を一時的に取得できません。もう一度お試しください。",
	图谱: "マップ",
	"在 LamTools 手机端输入此数字": "LamTools モバイル アプリにこの番号を入力してください",
	"在会话里让助手写下记忆，它就会出现在这里。": "アシスタントにセッションでメモリを書き込むように依頼すると、それがここに表示されます。",
	"在当前能力范围内自动批准（工作目录外仍会确认）": "現在の機能内で自動的に承認します (作業ディレクトリの外でも承認されます)",
	在线: "オンライン",
	"在聊天里说出你的想法，助手会一边问一边把方案写进「": "チャットであなたの考えを話すと、アシスタントが計画を「",
	在里面新建文件夹: "その中に新しいフォルダーを作成します",
	在里面新建记忆: "新しいメモリを作成します",
	处理中: "処理中",
	"处理中…": "処理中...",
	处理器类型: "プロセッサの種類",
	处理您的日常任务: "日々のタスクに取り組む",
	处理方式: "処理方法",
	备注: "備考",
	复位: "リセット",
	复制: "コピー",
	复制代码: "コードをコピー",
	复制回复: "返信をコピーします",
	复制失败: "コピーに失敗しました",
	"复制失败：当前环境无法访问剪贴板": "コピーに失敗しました: 現在の環境ではクリップボードにアクセスできません",
	"复制完整 ID": "完全な ID をコピーします",
	"复制完整会话 ID": "完全なセッション ID をコピーします",
	复制数字码: "数値コードをコピーします",
	复制消息: "メッセージをコピーします",
	复制路径: "パスをコピー",
	外观: "外観",
	外观模式: "外観モード",
	"外部搜索内核（subprocess / http）": "外部検索カーネル (サブプロセス/http)",
	多模态: "マルチモダリティ",
	"多模态（支持图片）": "マルチモダリティ (画像をサポート)",
	大纲: "概要",
	失败: "失敗",
	"如 AGENTS.md / CONTEXT.md": "AGENTS.md / CONTEXT.md など",
	"如 gpt-image-1 / flux 等，留空使用服务端默认": "gpt-image-1 / flux など、サーバーのデフォルトを使用するには空白のままにしてください",
	"如 my-skill（字母/数字/._-）": "私のスキルなど(文字/数字/._-)",
	"如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展": "独立した検索ツール (baidu-serp-api、SearXNG、openserp など) にアクセスする必要がある場合は、元の構成で展開します。",
	"如：我的 DeepSeek": "例: 私の DeepSeek",
	委派子代理: "代理サブエージェント",
	"委派子代理：{0}": "委任サブエージェント: {0}",
	子代理: "サブエージェント",
	"子代理 (agent)": "サブエージェント (エージェント)",
	"子代理 {0}": "サブエージェント {0}",
	子代理委派策略: "サブエージェント委任ポリシー",
	子代理资源统计: "サブエージェントのリソース統計",
	子代理运行中: "サブエージェントが実行中です",
	"子代理运行中：{0}": "サブエージェントが実行中: {0}",
	子层: "サブレイヤ",
	子工作流: "サブワークフロー",
	子文档: "サブドキュメント",
	"字段，例如：": "フィールド、例:",
	字节读取完成: "バイト読み取りが完了しました",
	学习: "学習",
	"学习、探索、温习": "学び、探索し、復習する",
	学科: "件名",
	"安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。": "セキュリティ ゲートウェイが起動しています。 LAN はノイズを使用して暗号化され、パブリック ネットワーク接続はセルフホスト型リレーを介して行われます。",
	安全边界: "セキュリティ境界",
	安装: "インストール",
	"安装中…": "インストール中...",
	安装依赖: "依存関係をインストールする",
	安装包约: "インストールパッケージについて",
	"安装完成后 Sunday 会自动重新打开。": "日曜日は、インストール完了後に自動的に再開されます。",
	安装成功: "インストールは成功しました",
	"安装成功：{0}": "インストールが成功しました: {0}",
	安装插件: "プラグインをインストールする",
	"完全编辑、自动批准，并允许访问工作目录外": "完全な編集、自動承認、および作業ディレクトリ外へのアクセスの許可",
	完全访问: "フルアクセス",
	完全访问已包含: "フルアクセスが含まれています",
	"完全访问模式会临时允许访问工作目录之外的路径。": "フルアクセス モードでは、作業ディレクトリの外部のパスへのアクセスが一時的に許可されます。",
	完成: "完了",
	完整归档: "完全なアーカイブ",
	"完整归档导出失败：{0}": "完全なアーカイブのエクスポートに失敗しました: {0}",
	"完整归档已保存：{0}": "完全なアーカイブが保存されました: {0}",
	"完整归档正在准备中，请稍候。": "完全なアーカイブを準備中です。お待ちください。",
	"官方发现与 Relay 必须登录": "公式ディスカバリと Relay にはログインする必要があります",
	官方模板: "公式テンプレート",
	定时任务: "スケジュール",
	"定时任务 › {0}": "スケジュールされたタスク › {0}",
	"定时任务 › 新建任务": "スケジュールされたタスク › 新しいタスクの作成",
	"定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。 点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。": "スケジュールされたタスクは、エージェントに与えられる長期的な指示です。時間になるとエージェントは自動的に作業を開始し、完了すると結果がセッションに残ります。右上隅にある「スケジュールされたタスクを作成」をクリックするか、チャットで「毎日9時に○○をする」と直接言います。",
	定时任务模板: "スケジュールされたタスクのテンプレート",
	定时切换: "スケジュールされた切り替え",
	实时: "リアルタイム",
	实时预览: "ライブプレビュー",
	实测: "実測",
	审批: "承認",
	容器内没有可选元素: "コンテナーにはオプションの要素がありません",
	宽松: "緩い",
	密码: "パスワード",
	对话: "ダイアログ",
	导入: "インポート",
	"导入 JSON": "JSON をインポートする",
	"导入失败：{0}": "インポートに失敗しました: {0}",
	导入工作流: "インポートワークフロー",
	导出: "エクスポート",
	"导出失败（{0}）": "エクスポートに失敗しました ({0})",
	"导出失败：{0}": "エクスポートに失敗しました: {0}",
	将移除此处的: "ここで削除されます",
	"将丢弃：{items}。已完成的工具结果会保留，终止后不能继续。": "破棄されるもの：{items}。完了済みのツール結果は保持され、終了後は続行できません。",
	"尚未启动 Sub Agent": "サブエージェントはまだ起動されていません",
	"尚未生成配对码。": "ペアリング コードはまだ生成されていません。",
	尚未登录服务器账号: "サーバーアカウントにまだログインしていません",
	尚未评估: "まだ評価されていません",
	尚未连接: "まだ接続されていません",
	"尚未配对手机。": "電話機はまだペアリングされていません。",
	尝试: "試してください",
	就绪: "準備完了",
	局域网: "LAN",
	"局部图超过建议范围（{0} 节点 / {1} 条关系），已保持分页；当前布局在主线程分层计算。": "部分グラフは推奨範囲 ({0} ノード / {1} 関係) を超えており、ページングは維持されています。現在のレイアウトはメインスレッドで階層的に計算されます。",
	展开: "展開",
	搜索图层: "レイヤーを検索",
	没有匹配的图层: "一致するレイヤーがありません",
	吸附: "スナップ",
	辅助线: "ガイド",
	父级: "親",
	尺寸: "サイズ",
	宽度: "幅",
	高度: "高さ",
	填充: "フィル",
	内容适配: "内容に合わせる",
	固定值: "固定値",
	未设置: "未設定",
	最小: "最小",
	最大: "最大",
	背景透明度: "背景の不透明度",
	图片格式无法识别: "画像形式を認識できません",
	"SVG 不允许包含脚本": "SVG にスクリプトは含められません",
	"展开 ": "展開する",
	"展开 {0}": "{0}を展開します",
	"展开{0}分区": "{0} パーティションを展開します",
	展开全部会话: "すべてのセッションを展開します",
	"展开另外 {0} 个会话": "さらに {0} 個のセッションを展開します",
	展开最近会话: "最近の会話を展開する",
	展开运行详情: "実行の詳細を展開します",
	工作业务: "仕事のビジネス",
	工作区: "ワークスペース",
	"工作区域保持纯色，颜色只用于控件层级。": "作業領域を無地のままにし、色はコントロール レベルでのみ使用されます。",
	工作台: "ワークベンチ",
	"工作根目录：": "作業ルートディレクトリ:",
	工作模式列表: "動作モードリスト",
	工作模式详情: "作業モードの詳細",
	工作流: "ワークフロー",
	工作流不存在: "ワークフローが存在しません",
	工作流名称: "ワークフロー名",
	工作流对话: "ワークフローダイアログ",
	工作流有未保存修改: "ワークフローに保存されていない変更があります",
	工作流检查器: "ワークフローインスペクター",
	工作流画布: "ワークフローキャンバス",
	工作流画布操作: "ワークフローキャンバス操作",
	工作流缩略图: "ワークフローのサムネイル",
	工作流节点操作: "ワークフローノードの操作",
	工作流节点目录: "ワークフローノードディレクトリ",
	工作流触发器与激活: "ワークフローのトリガーとアクティブ化",
	工作流资源: "ワークフローリソース",
	工作流运行输入: "ワークフロー実行入力",
	工作流连线操作: "ワークフロー接続操作",
	工作流队列与历史: "ワークフローキューと履歴",
	工作环境: "作業環境",
	"工作环境：{0}": "作業環境: {0}",
	工作目录: "作業ディレクトリ",
	"工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。": "作業ディレクトリ外での読み取り、書き込み、およびコマンド ライン アクセスでは、最初に確認が求められ、承認後に実行されます。",
	工作目录外访问: "作業ディレクトリ外へのアクセス",
	"工作目录外访问设置保存失败，已回滚：{0}": "作業ディレクトリ外へのアクセス設定の保存に失敗したため、ロールバックされました: {0}",
	工作目录外需确认: "作業ディレクトリ外を確認する必要があります",
	工具: "ツール",
	"工具 {0} 不可用：请求了当前环境没有注册的工具。": "ツール {0} は使用できません: 現在の環境に登録されていないツールが要求されました。",
	工具不可用: "ツールが使用できません",
	"工具不可用：{0}": "ツールは使用できません: {0}",
	工具列表: "Tool list",
	工具执行前请求批准: "ツールの実行前に承認が要求されました",
	工具模式: "ツールモード",
	工具调用: "Tool call",
	工具集: "Toolset",
	左对齐: "left aligned",
	已中断: "中断",
	"已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。": "ここからフォークされたセッションが作成されました。会話履歴のみがコピーされ、ワー​​クスペースやランタイム状態はコピーされません。",
	已保存: "保存済み",
	"已保存，重启后端后生效。": "保存されました。バックエンドの再起動後に有効になります。",
	"已保存：{0}": "Saved: {0}",
	"已保留本地修改，正在重试保存…": "ローカルの変更が保持されているため、保存を再試行しています...",
	已信任: "Trusted",
	已修改: "Modified",
	已停用: "無効です",
	"已停用。": "無効です。",
	已停用触发器: "Trigger disabled",
	已允许: "許可されています",
	已关闭: "終了",
	已创建任务: "Task created",
	"已创建：{0}": "Created: {0}",
	"已删除此轮及之后的对话；文件与成果保持不变。": "このラウンドとその後の会話は削除されました。ファイルと結果は変更されません。",
	"已加入队列：{0}": "キューに登録されました: {0}",
	已压缩: "圧縮",
	"已发布 v": "公開済み v",
	已取消: "キャンセルされました",
	"已取消完整归档导出。": "完全なアーカイブのエクスポートがキャンセルされました。",
	已取消暴露: "露出がキャンセルされました",
	已取消队列运行: "キューの実行がキャンセルされました",
	已启用: "Enabled",
	已复制: "コピーされました",
	"已复制 {0} 个元素": "{0} 個の要素がコピーされました",
	"已复制完整会话 ID": "完全なセッション ID がコピーされました",
	已失联: "連絡が途絶えました",
	已完成: "完了",
	"已完成|已失败|已中断|已取消": "完了|失敗|中断|キャンセルされました",
	"已导入：{0}": "インポートされました: {0}",
	"已导出工作流 JSON": "ワークフロー JSON がエクスポートされました",
	"已导出：{0}": "Exported: {0}",
	已就绪: "準備完了",
	"已就绪 · 已配置密钥": "準備完了 · キーが設定されました",
	已开启: "有効",
	已截断: "切り詰められました",
	已打开: "すでに開いています",
	已收藏: "お気に入り",
	"已新增触发器，请填写配置后保存。": "新しいトリガーが追加されました。設定を入力して保存してください。",
	"已是最新版本（v": "すでに最新バージョン (v",
	"内部测试版，已跳过应用内更新检查（请用 update-constant.ps1 更新）": "内部テスト版のため、アプリ内更新はスキップされます（update-constant.ps1 で更新してください）。",
	已暂停: "一時停止中",
	"已暂停（单步）": "一時停止中 (シングルステップ)",
	已暴露: "公開されました",
	"已暴露：{0}": "公開されました: {0}",
	"已替换并激活。": "置き換えられ、アクティブ化されました。",
	已替换并激活触发器: "トリガーが置き換えられ、アクティブ化されました",
	已标记: "フラグが立てられました",
	"已添加 {0} 个目录": "{0} ディレクトリが追加されました",
	"已添加节点：{0}": "ノードが追加されました: {0}",
	"已清理 {0} 个队列/历史项": "{0} 個のキュー/履歴アイテムがクリアされました",
	"已激活。": "すでにアクティブ化されています。",
	已激活触发器: "トリガーがアクティブになりました",
	已登录: "すでにログインしています",
	已禁用: "無効です",
	已移除: "削除されました",
	"已粘贴 {0} 个元素": "{0} 個の要素が貼り付けられました",
	已获取: "取得しました",
	已设为默认模型: "すでにデフォルトのモデルとして設定されています",
	已评估但未通过: "評価されましたが失敗しました",
	"已读取：{0}": "読み取り: {0}",
	"已调用{0}个工具…": "{0} ツールが呼び出されました...",
	已跳过: "スキップされました",
	已运行: "すでに実行中です",
	已连接: "接続されました",
	已退出: "終了しました",
	已选: "選択済み",
	已选中容器: "コンテナが選択されました",
	"已通过，掌握{0}": "合格、マスター済み {0}",
	已配对移动设备: "モバイルデバイスがペアリングされました",
	已配对设备: "デバイスがペアリングされました",
	"已配置（留空保持原密钥）": "Already configured (leave blank to keep the original key)",
	已采用远端版本: "リモートバージョンが採用されました",
	"已重命名：{0}": "名前が変更されました: {0}",
	已锁定区域: "Region locked",
	布局: "レイアウト",
	带输入运行: "Run with input",
	常量: "定数",
	常量值: "Constant value",
	"并发 {0}": "同時実行性 {0}",
	并发上限: "同時実行制限",
	库根: "クガン",
	应用: "適用",
	建议: "提案",
	建议模型: "推奨モデル",
	"建议模型 {0}": "推奨モデル {0}",
	开启: "有効",
	"开启后生成设备身份和一次性六位数字配对码。": "Generate device identity and one-time six-digit pairing code after turning it on.",
	开启手机控制: "携帯電話制御を有効にする",
	开启网格吸附: "グリッド スナップを有効にする",
	开始: "開始",
	开始使用: "はじめに",
	"开始前需要配置一个模型供应商，让 Agent 能思考与回复。": "Before starting, you need to configure a model provider so that the Agent can think and reply.",
	"开始时间（可选）": "開始時刻 (オプション)",
	开始配置: "構成の開始",
	开工: "Start work",
	引导: "ブート",
	引擎: "Engine",
	引用: "Reference",
	"引用外部工作流，iterate 控制执行模式": "Reference to external workflow, iterate controls execution mode",
	归到文件夹: "フォルダーに戻る",
	归属此账号的设备: "このアカウントに属するデバイス",
	"当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明": "メイン モデルがテキスト モデルで、写真/ビデオなどの添付ファイルを理解する必要がある場合、能力プロンプト ワードにより、メイン エージェントがこのモデルを使用してサブエージェントに表示を委任するように指示されます。宣言されたもののみを表示",
	当前主题: "現在のトピック",
	当前会话: "現在のセッション",
	当前会话可临时切换: "The current session can be temporarily switched",
	当前会话说明: "現在のセッションの説明",
	"当前使用内置默认：{0}": "現在、組み込みのデフォルトを使用しています: {0}",
	当前供应商: "Current supplier",
	"当前全局基线：{0}": "現在のグローバル ベースライン: {0}",
	当前六位数字配对码: "現在の 6 桁のペアリング コード",
	当前六位配对码: "現在の 6 桁のペアリング コード",
	"当前内核：{0}": "現在のコア: {0}",
	当前显示: "現在表示されています",
	"当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。": "Relay is not currently configured, and the mobile phone cannot discover this computer based on the digital code alone;最初にリモートリレーサービスを設定してください。",
	"当前来源：全局配置": "現在のソース: グローバル構成",
	"当前来源：内置默认（未配置全局 guide）": "Current source: built-in default (global guide not configured)",
	"当前来源：继承全局 / 内置默认（未配置项目级 guide）": "Current source: inherited global/built-in default (no project-level guide configured)",
	"当前来源：项目配置": "現在のソース: プロジェクト構成",
	当前桌面工作环境: "現在のデスクトップ作業環境",
	当前模型组: "現在のモデルグループ",
	当前模式: "Current mode",
	当前模式由插件提供: "現在のモードはプラグインによって提供されています",
	"当前步骤：第 {0} 步，{1}，{2}": "現在のステップ: ステップ {0}、{1}、{2}",
	"当前没有 checklist": "現在チェックリストはありません",
	当前没有可分叉的会话: "現在フォーク可能なセッションはありません",
	当前没有可回退的会话: "There are currently no sessions to roll back",
	"当前没有可用的项目，无法打开文件": "There are currently no projects available and the file cannot be opened.",
	当前没有可编辑的会话: "現在編集可能なセッションはありません",
	当前没有排队运行: "現在キューに入れられた実行はありません",
	"当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 {0} 条。": "There is currently no project coverage, and the global baseline will be used; after a new project rule is added to the task type with the same name, it will be covered by the project. {0} 個のアイテムが現在有効です。",
	当前版本: "現在のバージョン",
	"当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。": "Current version and software updates (priority is given to reading the official website update list, and falling back to GitHub Releases when the official website is unreachable).",
	"当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）": "The current environment does not support drag-and-drop installation (please use Release URL to paste and install)",
	当前环境不支持文件导出: "File export is not supported in the current environment",
	当前环境不支持文件选择: "File selection is not supported in the current environment",
	当前环境不支持附件选择: "Attachment selection is not supported in the current environment",
	"当前笔记没有保存处理，修改仍保留。": "The current note has not been saved and the modifications are still retained.",
	当前组: "現在のグループ",
	"当前继承全局有效策略：{0}": "Currently inheriting the global effective policy: {0}",
	当前计划: "現在の計画",
	当前账号: "現在のアカウント",
	"当前选择：{0}": "現在の選択: {0}",
	当前配对码: "現在のペアリング コード",
	当前队列: "現在のキュー",
	当前项目: "現在のプロジェクト",
	"当前项目没有本地覆盖。": "The current project has no local overrides.",
	"当前项目覆盖：{0}": "現在のプロジェクトの対象範囲: {0}",
	"当前项目还没有可用会话。新建会话后即可开始工作。": "There are no sessions available for the current project.新しいセッションを作成して作業を開始します。",
	当前默认状态: "現在のデフォルト状態",
	待你选择: "あなたの選択を待っています",
	待处理: "保留中",
	待处理项: "保留中のアイテム",
	待定: "保留中",
	待审核: "レビュー保留中",
	待接入: "アクセスを待機しています",
	待评定: "評価保留中",
	待配置: "構成する必要があります",
	"待配置 · 缺少 API Key": "構成する必要があります · API キーがありません",
	循环: "ループ",
	"循环 (loop)": "ループ",
	必填: "必須",
	"必须与所选供应商的 API 基础 URL 一致。": "Must match the selected vendor's API base URL.",
	快捷操作: "クイック操作",
	快速开始: "クイックスタート",
	思索: "思考",
	思考: "思考",
	"思考中…": "考え中...",
	"思考了{0}s": "{0} の考え",
	思考了一会: "しばらく考え中",
	思考模式: "思考モデル",
	思考等级: "思考レベル",
	思考等级选项: "レベルのオプションについて考える",
	恢复: "回復",
	"恢复 {0}": "{0} を復元",
	恢复到成果库: "結果ライブラリに復元",
	恢复默认: "デフォルトに戻す",
	"想了解什么？": "何を知りたいですか?",
	"想如何整理笔记…": "メモを整理する方法...",
	"想学什么…": "何を学びたいですか...",
	成员: "メンバー",
	成果: "結果",
	成果列表: "結果リスト",
	成果库: "結果ライブラリ",
	成果筛选: "結果のフィルタリング",
	"我想学{0}，给我讲一下": "{0} について学びたいので、教えてください。",
	"或粘贴 GitHub Release URL：": "または、GitHub リリース URL を貼り付けます。",
	截止: "期限",
	"所选目录在工作区之外，已保留绝对路径": "The selected directory is outside the workspace and the absolute path has been reserved",
	手动: "マニュアル",
	手动触发无需排程: "スケジュールなしの手動トリガー",
	手动运行: "手動で実行します",
	"手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。 自动送达（账号直传）尚未接入，先用导出／导入这一步。": "携帯電話で計画を立て、コンピュータで作業を開始: 計画は最初に携帯電話に保存され、デスクトップにインポートされた後に確認および実行できます。自動配信(アカウント直接転送)はまだ接続されていません。最初にエクスポート/インポートのステップを使用してください。",
	手机控制: "モバイル",
	"手机控制命令将在桌面 Tauri 运行时启用": "デスクトップ Tauri の実行中にモバイル コントロール コマンドが有効になります",
	"手机控制命令将在桌面 Tauri 运行时启用。": "デスクトップ Tauri の実行中に電話制御コマンドが有効になります。",
	手机控制未能启动: "携帯電話制御の開始に失敗しました",
	"手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。": "携帯電話がデジタル コードを送信した後、Relay は接続メタデータのみを解析します。実際のペアリング認証とセッション データは、依然としてノイズ暗号化トンネルを通じて完了します。",
	"手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。": "携帯電話はまだメモリ ディレクトリに接続していません。アシスタントにメモリ ツールを使用してセッション内で整理するか、デスクトップに接続してここを参照するように依頼してください。",
	手机配对: "携帯電話のペアリング",
	打开: "開く",
	"打开 ": "開く",
	"打开 {0}": "{0} を開きます",
	"打开 {0} 的项目记忆": "{0} のプロジェクト メモリを開きます",
	"打开「{0}」失败：{1}": "「{0}」を開けませんでした: {1}",
	"打开会话 {0}": "セッション {0} を開きます",
	打开右侧面板: "右側のパネルを開きます",
	"打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。": "開いた後、システムがアイドル スリープに入るのを防ぎ (手動スリープと閉じたスリープは影響を受けません)、長時間のタスクは中断されません。",
	"打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。": "開始後、モデルの質問カードに 5 分以上誰も回答しない場合、「ユーザー スキップ」が返され、現在のラウンドが続行されます。あなたの承認が必要な承認カードは影響を受けず、あなたの処理を待っています。",
	"打开完整设置（账号与设备）": "完全な設定 (アカウントとデバイス) を開く",
	打开工作区: "ワークスペースを開く",
	打开左侧会话栏: "左側の会話バーを開く",
	"打开快捷操作，当前模式 {0}": "ショートカット操作を開く、現在のモード {0}",
	打开文件夹: "フォルダーを開く",
	"打开文件夹 {0}": "フォルダー {0} を開きます",
	打开的工作流: "ワークフローを開く",
	"打开笔记 {0}": "メモ {0} を開きます",
	打开视窗: "ウィンドウを開く",
	打开账号与设备: "アカウントとデバイスを開く",
	打开附件失败: "添付ファイルを開けませんでした",
	"打开附件选择器失败：{0}": "添付ファイル セレクターを開けませんでした: {0}",
	"打开项目 {0}": "プロジェクト {0} を開きます",
	执行: "実行",
	"执行 Python 脚本，并通过端口传递变量。": "Python スクリプトを実行し、ポート経由で変数を渡します。",
	执行中: "実行中",
	执行前显示给用户的状态文字: "実行前にユーザーに表示されるステータス テキスト",
	"执行动作？": "アクションを実行しますか?",
	执行步骤: "ステップの実行",
	"执行进度：{0}": "実行の進行状況: {0}",
	扩展: "拡張子",
	扩展提示: "拡張機能プロンプト",
	"扩展自身的审批等级与 hard block 由各自的管理入口负责。": "拡張機能自体の承認レベルとハード ブロックは、それぞれの管理ポータルによって処理されます。",
	"扫描中…": "スキャン中...",
	扫描目录: "ディレクトリをスキャンします",
	批准: "承認されました",
	技能: "スキル",
	"技能加载后 Agent 应遵循的完整指引……": "スキルのロード後にエージェントが従うべき完全なガイドライン...",
	把这份方案交给当前会话执行: "このプランを現在のセッションに渡して実行します",
	折叠: "折りたたむ",
	"折叠 {0}": "{0}を折りたたむ",
	"折叠{0}分区": "{0} パーティションを折りたたむ",
	折叠最近会话: "最近の会話を折りたたむ",
	拍摄一张新照片: "新しい写真を撮ります",
	拒绝: "拒否",
	"拖动 {0} 模块排序": "{0} モジュールをドラッグして並べ替えます",
	拖动排序: "ドラッグして並べ替えます",
	拖动调整宽度: "ドラッグして幅を調整します",
	拖动调整宽高: "ドラッグして幅と高さを調整します",
	拖动调整高度: "ドラッグして高さを調整します",
	"拖拽 .zip 文件到此处安装": ".zip ファイルをここにドラッグ アンド ドロップしてインストールします",
	拖拽到这里上传: "ここにドラッグ アンド ドロップしてアップロードします",
	指令: "コマンド",
	"指令…": "コマンド...",
	指标: "インジケーター",
	按供应商: "サプライヤー別",
	按供应商分类的模型: "サプライヤー別のモデル",
	"按修改时间（新到旧）": "変更時刻順 (新しいものから古いものへ)",
	按名称: "名前による",
	"按工作流 input_params 传入": "ワークフローに従って input_params を渡します",
	"按条件选择后续分支。": "後続の分岐を条件付きで選択します。",
	按清单使用工具: "リストのツールを使用する",
	按状态筛选: "ステータスによるフィルター",
	按类型筛选: "タイプによるフィルター",
	按组: "グループ別",
	按组分类的模型: "グループ別のモデル",
	"按组新增模型时必须填写 API 基础 URL": "グループごとに新しいモデルを追加する場合、API ベース URL を入力する必要があります",
	按角色筛选: "ロールによるフィルター",
	"按计划运行任务，或在需要时随时执行。": "タスクをスケジュールに従って実行するか、必要に応じていつでも実行します。",
	"换个关键词再试。": "キーワードを変更して再試行してください。",
	换个关键词试试: "キーワードを変更してみてください",
	排队: "キューイング",
	消息发送: "メッセージ送信",
	直接引导: "すぐガイドする",
	"Enter 发送方式": "Enter の送信方法",
	"打开时直接按 Enter 会把消息立即交给当前回合；关闭时直接按 Enter 先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种。会话空闲时两个键都开新回合，两个键都不会改动已排队的项。": "オンにすると Enter でメッセージを現在のターンへすぐ渡します。オフにすると Enter は入力キューに入り、現在のターン終了後に順番に送られます。Ctrl+Enter は常に逆の動作です。セッションが待機中のときはどちらのキーも新しいターンを開始し、どちらのキーも待機中の項目には触れません。",
	"Enter 直接引导": "Enter ですぐガイドする",
	"当前：Enter 直接引导，Ctrl+Enter 排队": "現在：Enter はすぐガイド、Ctrl+Enter はキュー",
	"当前：Enter 排队，Ctrl+Enter 直接引导": "現在：Enter はキュー、Ctrl+Enter はすぐガイド",
	"会话正在运行时发送消息的去向：直接引导会把消息立即交给当前回合；排队会先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种，且两个键都不会改动已排队的项。": "セッション実行中にメッセージを送る先の設定：「すぐガイドする」は現在のターンへ即時に渡します。「キューイング」は入力キューに入り、現在のターン終了後に順番に送られます。Ctrl+Enter は常に逆の動作になり、どちらのキーも待機中の項目には触れません。",
	"排队项，可拖拽调整顺序": "キュー項目（ドラッグで並べ替え）",
	拖拽调整顺序: "ドラッグで並べ替え",
	"排队失败：{0}": "キューイングに失敗しました: {0}",
	"排除的默认上下文文件（except）": "除外されたデフォルトのコンテキスト ファイル (例外)",
	接口类型: "インターフェイスの種類",
	接口类型与适配参数: "インターフェースのタイプと適応パラメータ",
	"接收 {0} 消息失败": "{0} メッセージの受信に失敗しました",
	"接收工作流输入。": "ワークフロー入力を受信します。",
	控件: "コントロール",
	控制: "コントロール",
	"控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。": "ファイル操作を制御するためのデフォルトのスコープ。リスクの高い規則は日曜日まで引き続き施行される。",
	"控制新会话的默认权限；当前任务可以在输入框中临时调整。": "新しいセッションのデフォルトの権限を制御します。現在のタスクは入力ボックスで一時的に調整できます。",
	"控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。": "モデルに表示されるツールと、ツールが思考/実行モードでどのように公開されるかを制御します。",
	"控制过程行前的常规、运行与完成图标；等待和错误仍使用状态色。": "プロセスラインの前にある通常、実行、および完了のアイコンを制御します。 wait と error では引き続きステータス カラーが使用されます。",
	推理: "推論",
	推理预算: "推論予算",
	"描述（description）": "説明",
	提交: "送信",
	"提交中…": "送信中...",
	"提交数据必须是 JSON 对象": "送信されたデータは JSON オブジェクトである必要があります",
	"提交数据必须是有效 JSON": "送信されたデータは有効な JSON である必要があります",
	"提交数据（JSON）": "データの送信 (JSON)",
	提示文本: "プロンプトテキスト",
	提示文本不能为空: "プロンプトテキストを空にすることはできません",
	提问: "質問する",
	提问自动继续: "質問は自動的に続行されます",
	插件: "プラグイン",
	"插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件可禁用、不可卸载；每个插件按平台分类（通用 / 桌面端专用 / 移动端专用），本机只列出适用的部分。": "プラグイン = ツール/スキル/フック/MCP の統合インストール単位。組み込みプラグインは無効にすることができ、アンインストールすることはできません。各プラグインはプラットフォーム (ユニバーサル/デスクトップ固有/モバイル固有) ごとに分類されており、該当する部分のみがここにリストされています。",
	"插件与 MCP": "プラグインと MCP",
	"插件与 MCP 的 hard block 不能从此页解除。": "プラグインと MCP のハード ブロックをこのページから解除できません。",
	更多插件: "その他のプラグイン",
	在分屏中打开: "分割表示で開く",
	在右侧分屏中打开: "右側の分割表示で開く",
	在下方分屏中打开: "下側の分割表示で開く",
	插件分区: "プラグインパーティション",
	插件功能不可用: "プラグイン機能は使用できません",
	插件未返回有效数据: "プラグインは有効なデータを返しませんでした",
	"插件目录或 .zip 路径": "プラグイン ディレクトリまたは .zip パス",
	"插值）": "補間)",
	"插入 Callout": "吹き出しの挿入",
	"插入 Mermaid 图": "人魚図の挿入",
	插入代码块: "コードブロックを挿入",
	插入公式: "数式を挿入",
	插入引用: "参照を挿入",
	插入表格: "テーブルの挿入",
	搜索: "検索",
	"搜索 {0}": "{0}を検索",
	"搜索不可用：{0}": "検索は利用できません: {0}",
	"搜索中…": "検索中...",
	"搜索了{0}次": "{0} 回検索されました",
	"搜索了{0}次…": "{0} 回検索されました...",
	"搜索任务、插件或文件": "タスク、プラグイン、またはファイルを検索します",
	搜索供应商: "サプライヤーの検索",
	搜索内容: "コンテンツの検索",
	"搜索名称、分类或说明": "名前、カテゴリ、または説明を検索します",
	"搜索名称、路径或来源…": "名前、パス、またはソースを検索します...",
	搜索工作区索引: "ワークスペースインデックスの検索",
	搜索工具: "検索ツール",
	搜索成果库: "検索結果ライブラリ",
	"搜索插件未启用。到「插件」页启用 websearch 后可用。": "検索プラグインが有効になっていません。 「プラグイン」ページでウェブ検索を有効にすると利用可能になります。",
	搜索服务响应正常: "検索サービスは正常に応答します",
	搜索模型: "モデルの検索",
	搜索模型组: "モデルグループの検索",
	搜索模式: "検索モード",
	搜索结果: "検索結果",
	搜索节点: "検索ノード",
	搜索范围: "検索範囲",
	搜索记忆: "メモリの検索",
	搜索资料库: "ライブラリの検索",
	搜索项目: "項目の検索",
	搜索项目和会话: "プロジェクトとセッションを検索する",
	撤回: "撤回",
	撤销: "元に戻す",
	撤销后设备立即失去访问权限: "取り消し後、デバイスはすぐにアクセスを失います。",
	"撤销（Ctrl/Cmd+Z）": "元に戻す (Ctrl/Cmd+Z)",
	操作: "操作",
	操作失败: "操作が失敗しました",
	"操作失败：{0}": "操作が失敗しました: {0}",
	支持推理: "推論のサポート",
	"支持注释（JSONC），保存后即时生效。": "コメント (JSONC) をサポートしており、保存後すぐに有効になります。",
	"收到了 {0} 的消息": "{0} からメッセージを受信しました",
	收藏: "コレクション",
	"收藏：{0}": "コレクション: {0}",
	收起: "折りたたむ",
	"收起 ": "折りたたむ",
	"收起 {0}": "{0}を折りたたむ",
	收起会话: "セッションを折りたたむ",
	收起计划: "計画を折りたたむ",
	收起运行详情: "実行の詳細を折りたたむ",
	放大: "ズームイン",
	放大对话: "会話を拡大する",
	放弃: "諦める",
	放弃修改: "変更を放棄します",
	"放弃未保存的修改？": "未保存の変更を破棄しますか?",
	放弃本地修改并采用远端版本: "ローカルの変更を放棄し、リモート バージョンを採用する",
	"敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。": "機密パス (.env、SSH 認証情報など) の書き込みと編集は依然としてブロックされます。",
	教学示意图: "ティーチング図",
	教学配图: "絵を教える",
	数据: "データ",
	整理: "整理する",
	文件: "ファイル",
	"文件 {0}": "ファイル {0}",
	"文件 · ": "ファイル ·",
	文件名: "ファイル名",
	"文件名（如 TEAM_RULES.md）": "ファイル名(TEAM_RULES.mdなど)",
	文件夹: "フォルダー",
	文件夹名: "フォルダー名",
	文件夹名称: "フォルダー名",
	文件改动: "ファイルの変更",
	"文件结束 · ": "ファイルの終わり ·",
	文件缺失: "ファイルがありません",
	文件边界: "ファイル境界",
	文本: "テキスト",
	文本操作: "テキスト操作",
	文本记录: "テキストレコード",
	文本颜色: "文字の色",
	"文本（不支持图片）": "テキスト (画像はサポートされていません)",
	文档: "ドキュメント",
	文档大纲: "ドキュメントのアウトライン",
	文档知识: "ドキュメントの知識",
	斜体: "斜体",
	新任务: "新規タスク",
	新会话将从这里开始: "ここで新しいセッションが開始されます",
	新会话默认: "新しいセッションのデフォルト",
	"新供应商需要填写名称和 API Key": "新しいサプライヤーは名前と API キーを入力する必要があります",
	新增: "新規",
	"新增 Hook": "新しいフックを追加",
	"新增 {0} 行": "{0} 行を追加しました",
	"新增一个模式后，就可以设置它能使用的工具。": "新しいモードを追加した後、使用できるツールを設定できます。",
	新增供应商: "新しいサプライヤーを追加",
	新增模型: "新しいモデルを追加",
	新增模式: "新しいモード",
	新增第一条角色分配: "最初のロール割り当てを追加します",
	新增触发器: "新しいトリガーを追加します",
	新建: "新規",
	新建任务: "新しいタスクを作成する",
	新建会话: "新規会話",
	新建定时任务: "新しいスケジュールされたタスクを作成する",
	新建工作流: "新しいワークフローを作成する",
	新建技能: "新しいスキルを作成する",
	新建文件夹: "新しいフォルダーを作成します",
	"新建文件夹…": "新しいフォルダーを作成します...",
	新建方案: "新しいスキームを作成する",
	新建模型组: "新しいモデルグループを作成します",
	新建节点: "新しいノードを作成します",
	新建记忆: "新しいメモリを作成する",
	新建项目: "新規プロジェクト",
	方案: "プラン",
	方案传输: "スキーム転送",
	方案名称: "スキーム名",
	"方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态": "プランの準備ができるまで、プランを開始できません — チャットでアシスタントに「開始する準備ができました」と言うと、プランのステータスが更新されます",
	方案编辑: "スキームの編集",
	方案阅读: "スキームの読み取り",
	无依赖: "依存関係はありません",
	无多模态模型: "マルチモーダル モデルがありません",
	无工具: "ツールがありません",
	无序列表: "順序なしリスト",
	无技能: "スキルがありません",
	"无法创建模型组 {0}": "モデル グループ {0} を作成できません",
	"无法打开学习会话，请重试": "学習セッションを開けません。もう一度お試しください。",
	"无法打开：{0}": "開けません: {0}",
	无法显示: "表示できません",
	"无法更新连线：端口类型不兼容或端口不存在": "接続を更新できません: ポートタイプに互換性がないか、ポートが存在しません",
	"无法读取文本：{0}": "テキストを読み取れません: {0}",
	"无法连接服务器：{0}": "サーバーに接続できません: {0}",
	"无法连接：端口类型不兼容或端口不存在": "接続できません: 互換性のないポートタイプまたはポートが存在しません",
	无钩子: "フックがありません",
	无需压缩: "圧縮は必要ありません",
	日: "日",
	日出渐变: "日の出のグラデーション",
	日历: "カレンダー",
	日历触发器需要时间: "カレンダーのトリガーに時間がかかります",
	日历频率: "カレンダーの頻度",
	日志: "ログ",
	日期: "日付",
	时区: "タイムゾーン",
	时间: "時間",
	"时间 {0}": "時間 {0}",
	映射: "マッピング",
	"显式替换现有激活，并固定到当前 revision": "既存のアクティベーションを明示的に置き換え、現在のリビジョンに固定します",
	显示名称: "表示名",
	显示已移除: "ディスプレイが削除されました",
	显示更早的过程: "古いプロセスを表示します",
	显示模块: "ディスプレイモジュール",
	晨会摘要: "朝礼の概要",
	晨宵: "朝と夕方",
	智能: "インテリジェンス",
	智能体: "エージェント",
	"智能体目标…": "エージェントのターゲット...",
	"暂不可用：{0}": "一時的に利用できません: {0}",
	暂停: "一時停止",
	"暂停工作流，等待人工批准或拒绝。": "ワークフローは手動による承認または拒否の保留中一時停止されました。",
	暂无: "まだありません",
	暂无上下文: "コンテキストなし",
	暂无上下文统计: "コンテキスト統計がまだありません",
	暂无会话: "まだセッションがありません",
	"暂无内容，创建一个开始。": "コンテンツがまだありません。最初にコンテンツを作成してください。",
	"暂无可显示的 Sub Agent 事件。": "表示するサブエージェント イベントがありません。",
	暂无可添加的模型: "追加するモデルはまだありません。",
	暂无可用工具: "利用可能なツールはまだありません",
	暂无可用数据: "利用可能なデータはまだありません",
	暂无可用模型: "利用可能なモデルはまだありません",
	"暂无可用模型，可手动输入模型 ID": "利用可能なモデルはまだありません。モデル ID を手動で入力できます",
	暂无已登记项目: "まだプロジェクトが登録されていません",
	"暂无已登记项目。": "登録されたプロジェクトはまだありません。",
	"暂无已移除的成果。": "結果はまだ削除されていません。",
	暂无待处理任务: "保留中のタスクはまだありません",
	"暂无消息，发送一个任务。": "まだメッセージがありません。タスクを送信してください。",
	"暂无笔记关系。": "ノート関係はまだありません。",
	"暂无符合筛选条件的成果。": "現在、フィルター条件を満たす結果はありません。",
	暂无节点: "まだノードがありません",
	"暂无触发器。新增后可配置手动或定时入口。": "まだトリガーがありません。追加後、手動またはスケジュールされた入場を設定できます。",
	"暂无资源统计。": "リソース統計がまだありません。",
	"暴露为 Agent 工具": "エージェントツールとして公開",
	更多: "詳細",
	更新: "アップデート",
	"更新 v{0} 已下载并校验，点击安装": "アップデート v{0} がダウンロードされ、確認されました。クリックしてインストールしてください",
	更新于: "更新日",
	更新任务清单: "タスクリストを更新します",
	更新定时任务失败: "スケジュールされたタスクの更新に失敗しました",
	"更新模型标识、能力和运行参数。": "モデルの識別、機能、および動作パラメータを更新します。",
	更新计划: "計画の更新",
	"更新连接信息，已有密钥不会被覆盖。": "接続情報を更新します。既存のキーは上書きされません。",
	替换并激活: "置換してアクティブ化する",
	最低思考强度: "最小の思考強度",
	"最低思考强度 {0}": "最小思考強度 {0}",
	最后一个: "最後",
	最多运行次数: "最大実行数",
	最大化: "最大化",
	最大并发: "最大同時実行数",
	最大输出: "最大出力",
	最大运行次数: "最大実行数",
	"最大运行次数（可选）": "最大実行数 (オプション)",
	最大迭代: "最大反復回数",
	最小化: "最小化",
	"最小间隔（秒）": "最小間隔 (秒)",
	最新版本: "最新バージョン",
	最近: "最近",
	"最近一次 {0}": "最新の {0}",
	最近任务: "最近のタスク",
	最近打开: "最近オープンしました",
	最近项目: "最近のプロジェクト",
	最高思考强度: "最高の思考強度",
	"最高思考强度 {0}": "最高の思考強度 {0}",
	有序列表: "順序付きリスト",
	有效期至: "まで有効",
	有新版本可用: "新しいバージョンが利用可能です",
	有未保存修改: "未保存の変更があります",
	有未保存的修改: "未保存の変更があります",
	服务器: "サーバー",
	"服务器地址必须使用 HTTP 或 HTTPS": "サーバー アドレスは HTTP または HTTPS を使用する必要があります",
	服务器地址格式无效: "サーバーアドレスの形式が無効です",
	"服务器未返回有效的桌面 Node": "サーバーが有効なデスクトップ ノードを返しませんでした",
	"服务器请求失败（{0}）": "サーバーリクエストが失敗しました ({0})",
	服务器账号: "サーバーアカウント",
	服务器返回了无效的登录凭据: "サーバーが無効なログイン資格情報を返しました",
	服务地址: "サービスアドレス",
	未上报: "報告されていません",
	未上报缓存: "キャッシュが報告されませんでした",
	未保存: "保存されていません",
	未关联供应商: "サプライヤーが関連付けられていません",
	未分组: "グループ化されていません",
	"未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。": "フックが見つかりません。 「フックの追加」をクリックしてイベントフックを作成するか、「オリジナル構成」に切り替えてJSONを手動で記述します。",
	"未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为": "スキルが見つかりません。 「新しいスキル」をクリックして作成するか、SKILL.mdをスキルディレクトリ(デスクトップの場合)に置きます。",
	未发现新目录: "新しいディレクトリが見つかりません",
	未启用: "有効になっていません",
	未命中: "欠落しました",
	未命名定时任务: "名前のないスケジュールされたタスク",
	未命名工作流: "名前のないワークフロー",
	未命名来源: "名前のないソース",
	未命名节点: "名前のないノード",
	未命名运行: "名前のない実行",
	未命名项目: "名前のない項目",
	"未安装 RAG 插件；可尝试兼容搜索": "RAG プラグインがインストールされていません。互換性検索を試してください",
	未找到匹配的项目或会话: "一致するプロジェクトまたはセッションが見つかりません",
	"未找到对应笔记，无法导航。": "対応するメモが見つからないため、移動できません。",
	"未找到该消息（可能已被删除或属于子会话）": "メッセージが見つかりませんでした (削除されたか、サブセッションに属している可能性があります)",
	"未找到：{0}": "見つかりません: {0}",
	未指定: "指定されていません",
	未提供命令: "コマンドが提供されていません",
	"未提取到正文摘要。": "テキストの概要が抽出されませんでした。",
	未检查: "チェックされていません",
	未激活: "アクティブ化されていません",
	未登录: "ログインしていません",
	未知: "不明",
	未知命令: "不明なコマンドです",
	未知触发方式: "不明なトリガーメソッドです",
	未获取: "取得できませんでした",
	"未获得收益 · ": "特典は受け取れません ·",
	"未记录任务内容。": "タスクの内容が記録されません。",
	未设置事件: "イベントが設定されていません",
	未设置时间: "時間が設定されていません",
	"未设置（可在设置中调整）": "未設定 (設定で調整可能)",
	未运行: "実行されていません",
	未连接到搜索服务: "検索サービスに接続されていません",
	未选择: "未選択",
	未配置: "未構成",
	"未配置（使用内置兜底：{0}）": "未構成 (内蔵カバーを使用: {0})",
	"未回答的子代理提问 {count} 个": "未回答のサブエージェント質問 {count} 件",
	未完成的步骤: "未完了のステップ",
	"本地 zip 路径": "ローカル zip パス",
	本地目录: "ローカルディレクトリ",
	本机: "ネイティブ",
	"本机命令工具使用的 shell": "ネイティブ コマンド ツールで使用されるシェル",
	本机身份: "ネイティブ ID",
	本轮产出: "このラウンドの出力",
	"机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。": "マシンのメモリ不足により現在のラウンドが中断されると、Sunday はその理由を説明し、「利用可能なメモリが利用可能なメモリより大きい場合は自動的に続行します」と表示します。記憶が復元されると、同じセッションで新しいラウンドが自動的に開かれ、最大 3 回まで継続されます。最初に新しいメッセージを送信しても、自動的に続行されなくなります。",
	权限: "権限",
	"权限偏好保存失败：{0}": "権限設定を保存できませんでした: {0}",
	权限审批: "権限の承認",
	"权限审批与输入框保持一致；工具清单由“工具模式”管理。": "権限の承認は入力ボックスと一致しています。ツールリストは「ツールモード」で管理します。",
	权限审批选项: "権限承認オプション",
	"权限模式保存失败，已回滚：{0}": "権限モードの保存に失敗しました。ロールバックされました: {0}",
	条件: "条件",
	条关系: "関係",
	条用户指令: "ユーザーコマンド",
	来源: "ソース",
	来自子代理: "サブエージェントから",
	松开以安装: "インストールするリリース",
	松开鼠标上传附件: "マウスを放して添付ファイルをアップロードします",
	极光渐变: "オーロラグラデーション",
	极高: "最大",
	构建稳定的工作流程: "安定したワークフローを構築する",
	查看: "ビュー",
	"查看 git 差异": "git diff を表示する",
	"查看 git 状态": "git ステータスの表示",
	查看全文: "全文表示",
	"查看其余 ": "残りを表示",
	"查看其余 {0} 步": "残りの {0} ステップを表示します",
	查看发布说明: "リリース ノートを表示する",
	查看官方文档: "公式ドキュメントを表示する",
	标准: "標準",
	标准输出: "標準出力",
	标记: "マーク",
	标题: "タイトル",
	"标题（name）": "タイトル(名前)",
	框架: "フレーム",
	"框架.{0}": "フレーム。{0}",
	桌面端专用: "デスクトップのみ",
	"档位 全局档": "ギアグローバルファイル",
	"档位 项目档": "ファイルプロジェクトファイル",
	"检查中…": "チェック中...",
	"检查失败：": "チェックに失敗しました:",
	检查更新: "アップデートを確認する",
	"检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。": "過去 24 時間のコードとデータの変更を確認し、実行エラー、データ損失、権限違反などのリスクを特定し、コードの場所と修復の提案を添付します。",
	检查连接: "接続を確認してください",
	"检测到版本冲突，但无法读取远端版本：{0}": "バージョンの競合が検出されましたが、リモート バージョンを読み取ることができません: {0}",
	"检测到版本冲突，远端版本暂不可读取": "バージョンの競合が検出されました。リモート バージョンは一時的に読み取れません",
	森林渐变: "森のグラデーション",
	棱镜渐变: "プリズムグラデーション",
	模型: "モデル",
	"模型 ID": "モデルID",
	"模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。": "モデル、MCP、コマンド ツール、Web クローリングと検索、プラグインのインストール、およびソフトウェア アップデートのダウンロードのエクスポート トラフィックはすべてこのプロキシを経由します。アプリケーション インターフェイスの Web ページ (レンダリング層) は、システムのプロキシ設定に従います。空白のままにすると、これらのフローは直接接続され、システム環境変数は読み取られません。ローカル アドレス (localhost、127.0.0.1、::1) は常に直接接続されます。",
	模型与供应商: "モデル",
	"模型与供应商、外观主题、工具权限等应用配置。": "モデル、外観、ツールの権限などのアプリ設定。",
	模型与思考参数: "モデルと思考パラメータ",
	"模型与思考强度：{0} {1}": "モデルと思考の強度: {0} {1}",
	模型分类方式: "モデルの分類方法",
	"模型分类方式保存失败，已回滚：{0}": "モデル分類メソッドは保存に失敗したため、ロールバックされました: {0}",
	"模型列表加载失败，可手动输入": "モデルリストのロードに失敗しました。手動で入力できます。",
	"模型可同时存在于多个组；删除组不会删除模型。": "モデルは同時に複数のグループに存在できます。グループを削除してもモデルは削除されません。",
	模型已创建并加入分组: "モデルが作成され、グループに追加されました",
	模型已删除: "モデルが削除されました",
	模型已更新: "モデルが更新されました",
	模型已添加: "モデルが追加されました",
	"模型指令…": "モデルコマンド...",
	模型数量: "モデルの数",
	模型组: "モデルグループ",
	模型组列表: "モデルグループリスト",
	模型组已创建: "モデルグループが作成されました",
	模型组已删除: "モデルグループが削除されました",
	模型组已更新: "モデルグループが更新されました",
	模型组成员: "モデルグループメンバー",
	模型组成员已更新: "モデルグループのメンバーが更新されました",
	模型组空状态: "モデルグループが空のステータス",
	模型组详情: "モデルグループの詳細",
	模型能力: "モデルの機能",
	模型选项: "モデルオプション",
	模型配置: "モデル構成",
	模式: "モード",
	模式名: "スキーマ名",
	"模式名不能为空，已取消保存": "スキーマ名を空にすることはできません。保存はキャンセルされました",
	"模式名重复：{0}，已取消保存": "重複したスキーマ名: {0}、保存がキャンセルされました",
	模式说明: "モードの説明",
	模板: "テンプレート",
	模板入口: "テンプレートエントリ",
	横向分布: "水平分布",
	横向滚动表格: "水平スクロールテーブル",
	橙色: "オレンジ",
	次: "回",
	次数: "回",
	"次调用 ·": "呼び出し ·",
	"欢迎使用 Sunday": "日曜日へようこそ",
	正在: "現在",
	"正在下载 v{0}…": "{0} をダウンロード中...",
	"正在下载…": "ダウンロード中...",
	正在下载更新: "アップデートをダウンロードしています",
	"正在保存…": "保存中...",
	"正在保存项目更改…": "プロジェクトの変更を保存しています...",
	"正在停止…": "停止しています...",
	"正在准备完整归档，请稍候…": "完全なアーカイブを準備しています。お待ちください...",
	"正在创建…": "作成中...",
	正在刷新进程列表: "プロセスリストを更新しています",
	"正在加载…": "読み込み中...",
	正在加载历史消息: "履歴メッセージをロードしています",
	"正在加载工具模式…": "ツールモードをロード中...",
	"正在加载成果库…": "結果ライブラリをロードしています...",
	正在加载更早消息: "古いメッセージをロードしています",
	"正在加载笔记…": "メモをロードしています...",
	正在压缩上下文: "コンテキストを圧縮しています",
	正在同步: "同期中",
	"正在回答…": "応答中...",
	正在处理: "処理中",
	"正在安装…": "インストール中...",
	正在安装更新: "アップデートをインストールしています",
	"正在打开…": "開いています...",
	"正在检查…": "チェック中...",
	"正在生成配对码…": "ペアリング コードを生成しています...",
	"正在读取 Sub Agent 记录...": "サブエージェント レコードを読み取り中...",
	"正在读取…": "読み取り中...",
	"正在读取后台进程…": "バックグラウンドプロセスを読み取り中...",
	"正在读取定时任务…": "スケジュールされたタスクを読み取り中...",
	"正在读取文本…": "テキストを読んでいます...",
	"正在读取记忆…": "メモリを読み取り中...",
	"正在读取资料库…": "ライブラリを読み取り中...",
	"正在读取项目…": "項目を読み取り中...",
	正在输出: "出力中",
	正常: "通常",
	正文: "テキスト",
	"正在运行或已暂停的子代理 {count} 个": "実行中または一時停止中のサブエージェント {count} 件",
	此容器: "このコンテナ",
	"此操作不可撤销，将": "この操作は元に戻すことができません。",
	"此文件将交给系统默认应用处理。": "このファイルは、処理のためにシステムのデフォルト アプリケーションに渡されます。",
	此模块暂不可用: "このモジュールは一時的に使用できません",
	此模块未启用: "このモジュールは有効になっていません",
	此电脑: "このコンピュータ",
	此节点: "このノード",
	此节点暂不支持可视化配置: "このノードは現在、ビジュアル構成をサポートしていません",
	步: "ステップ",
	步骤: "手順",
	"步：": "ステップ:",
	每: "すべて",
	"每 {0} 秒": "{0} 秒ごと",
	每天: "毎日",
	"每天 {0}": "毎日{0}",
	每月: "毎月",
	"每月 {0} 日 {1}": "毎月 {0} 日 {1}",
	"每月日期必须是 1 到 31": "毎月の日は 1 ~ 31 である必要があります",
	每月第几天: "月の日",
	每次新建: "毎回新規",
	每行一个: "1 行に 1 つ",
	"每隔（秒）": "(秒)ごと",
	水平居中: "水平方向に中央揃え",
	"汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。": "セッションの進行状況、完了した項目、昨日以降のフォローアップ項目を要約し、6 項目以内の口頭要約を生成します。読み取り専用の分析。ファイルは変更されません。",
	汇聚: "集約",
	"汇聚具名输入并收集为对象。": "名前付き入力を集約し、オブジェクトに収集します。",
	"没有匹配「{0}」的结果 — 换个关键词，或切到「全部」看看其他范围": "「{0}」に一致する結果はありません — キーワードを変更するか、「すべて」に切り替えて他の範囲を表示してください",
	没有匹配的供应商: "一致するサプライヤーがありません",
	没有匹配的模型: "一致するモデルがありません",
	没有匹配的模型组: "一致するモデル グループがありません",
	没有匹配的模式: "一致するパターンがありません",
	没有匹配的节点: "一致するノードがありません",
	没有匹配的项目: "一致するアイテムがありません",
	没有匹配结果: "一致する結果がありません",
	没有可切换的插件模式: "切り替えるプラグイン モードがありません",
	没有找到匹配的工具: "一致するツールが見つかりません",
	没有正在登记的后台进程: "バックグラウンドプロセスが登録されていません",
	没有长期后台进程: "長期的なバックグラウンドプロセスはありません",
	"注入优先级（越小越靠前）": "インジェクション優先度(小さいほど優先度が高くなります)",
	注入到上下文的提示文本: "ヒントテキストがコンテキストに挿入されました",
	注册: "登録",
	注释: "コメント",
	"注释.{0}": "コメント。{0}",
	浅色: "明るい色",
	浅色从: "明るい色",
	"浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。": "明るい色はグラファイト マークを運ぶためにアイボリー ホワイトを使用し、暗い色はグラファイト ベースとアイボリー マークに反転されます。",
	"浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。": "明るい色にはフォグブルーからクリームホワイト、暗い色には濃い緑から青黒の背景を使用し、他のインターフェイスレイヤーはニュートラルに保ちます。",
	浅色开始时间: "ライトカラー開始時間",
	测试: "テスト",
	测试失败: "テストが失敗しました",
	测试超时: "テストがタイムアウトしました",
	测试通过: "テストに合格しました",
	浏览: "参照",
	"浏览…": "参照...",
	"浏览了{0}个目录": "{0} ディレクトリを参照しました",
	"浏览了{0}个目录…": "{0} ディレクトリが参照されました...",
	浮梦: "浮かぶ夢",
	海洋渐变: "オーシャングラデーション",
	消息附件: "メッセージ添付ファイル",
	淡灰: "ライトグレー",
	深色: "ダーク",
	深色从: "暗い色から",
	深色开始时间: "ダークスタート時間",
	添加: "追加",
	"添加一个 OpenAI Compatible 或其他模型供应商": "OpenAI 互換または他のモデルのプロバイダーを追加する",
	添加一条简短说明: "短い説明を追加します",
	添加供应商: "サプライヤーの追加",
	添加到: "に追加",
	添加到当前会话: "現在のセッションに追加",
	添加到收藏: "お気に入りに追加",
	添加到文件夹: "フォルダーに追加",
	添加已有模型: "既存のモデルを追加",
	添加模型: "モデルの追加",
	"添加现有模型，或创建一个新模型": "既存のモデルを追加するか、新しいモデルを作成します",
	"添加节点…": "ノードを追加します...",
	"添加节点：{0}": "ノードを追加: {0}",
	添加计划: "プランの追加",
	添加附件: "添付ファイルを追加",
	清单: "リスト",
	清理历史: "履歴をクリア",
	"清理失败：{0}": "クリーンアップに失敗しました: {0}",
	清空全部: "すべてクリア",
	清除: "クリア",
	"清除“全部工具”后，可以单独选择需要开放的工具。": "[すべてのツール] をクリアした後、開く必要があるツールを個別に選択できます。",
	清除搜索: "検索をクリア",
	清除节点目录搜索: "ノードディレクトリ検索をクリアします",
	渐变角度: "勾配角度",
	温度: "温度",
	激活: "アクティブ化",
	"激活会固定当前工作流 revision": "アクティブ化すると、現在のワークフロー リビジョンが固定されます",
	"激活失败：{0}": "アクティブ化に失敗しました: {0}",
	"激活状态刷新失败：{0}": "アクティブ化ステータスの更新に失敗しました: {0}",
	"灰线：未上报缓存": "灰色の線: キャッシュが報告されません",
	灰色区压缩: "グレー領域の圧縮",
	灵感构思: "インスピレーションを与えるアイデア",
	"点击“生成配对码”开始配对。": "[ペアリング コードの生成] をクリックしてペアリングを開始します。",
	"点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。": "直接送信するオプションをクリックします。処理方法を書き留めて Enter キーを押すか、「送信」をクリックすることもできます。",
	"点此申请 API key": "API キーを申請するにはここをクリックしてください",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。": "次に、計画実行プロセスに従って、目標とステップを現在のセッションのリストにロードし、段階的に作業を開始します。",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工；方案文件的更新写回它原来的位置。": "次に、計画実行プロセスに従って、現在のセッションのリストに目標とステップをロードし、徐々に作業を開始します。計画ファイルの更新は元の場所に書き戻されます。",
	版本不符: "バージョンの不一致",
	版本信息: "バージョン情報",
	"版本；切换后立即生效。": "バージョン;切り替え直後から有効になります。",
	状态: "ステータス",
	"状态消息 (可选)": "ステータスメッセージ (オプション)",
	"状态：{0}": "ステータス: {0}",
	生图: "RAW画像",
	"生成 {0}": "{0} を生成します",
	生成中: "生成中",
	生成图片: "画像の生成",
	生成工具输入: "ツール入力の生成",
	生成配对码: "ペアリングコードの生成",
	"用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。": "LamTools モバイルを使用して、会話を表示し、タスクを続行し、承認を処理します。 Core は依然としてローカル アドレスのみをリッスンします。",
	用一句话说明要怎么处理: "何をすべきかを一文で説明してください",
	"用于侧边栏中的项目辨识。": "サイドバーでの項目の識別に使用されます。",
	用户: "ユーザー",
	用户上传: "ユーザーのアップロード",
	用户名: "ユーザー名",
	用户指令导航: "ユーザーコマンドナビゲーション",
	用户消息: "ユーザーメッセージ",
	电脑: "コンピューター",
	画布元素: "キャンバス要素",
	画布元素操作: "Canvas 要素の操作",
	画布布局工具: "キャンバスレイアウトツール",
	界面: "外観",
	界面密度: "インターフェース密度",
	界面语言: "表示言語",
	留空不限: "空白のままにする制限はありません",
	留空以保留现有密钥: "既存のキーを保持するには空白のままにしてください",
	留空时使用目录名称: "空のままにした場合はディレクトリ名を使用します",
	"留空时直连；填写后使用 http://127.0.0.1:端口。": "空白のままにした場合は直接接続。入力後に http://127.0.0.1: ポートを使用します。",
	登录: "ログイン",
	"登录 / 账号": "ログイン/アカウント",
	"登录后在手机上配对，这里会列出已配对的设备。": "ログイン後、電話機でペアリングします。ペアリングされたデバイスがここにリストされます。",
	"登录状态与已配对的设备。": "ペアリングされたデバイスのログインステータス。",
	的: "の",
	"的模型。": "のモデル。",
	"目录 ": "ディレクトリ",
	"目录名 + frontmatter name": "ディレクトリ名 + フロントマター名",
	"目录路径（工作区相对或绝对）": "ディレクトリ パス (ワークスペースの相対または絶対)",
	目标: "ターゲット",
	目标与待发送输入: "送信されるターゲットと入力",
	相关设置: "関連設定",
	相册: "フォトアルバム",
	相机: "カメラ",
	知识关系: "知識の関係",
	知识图谱: "ナレッジグラフ",
	知识层级: "知識階層",
	知道了: "分かりました",
	"确定删除“{0}”及其内部 {1} 个元素？此操作不可撤销。": "'{0}' とその中の {1} 要素を削除してもよろしいですか?この操作は元に戻すことができません。",
	确认: "確認",
	确认删除: "削除の確認",
	确认放弃修改: "変更を中止することを確認します",
	确认清理: "クリーンアップの確認",
	确认清理队列: "クリーンアップキューを確認します",
	确认移除: "削除を確認します",
	"确认（{0}秒）": "確認({0}秒)",
	禁止: "禁止されています",
	"禁用技能 {0}": "スキル {0} が無効になりました",
	"禁用插件 {0}": "プラグイン {0} を無効にする",
	离线: "オフライン",
	秒: "秒",
	移出组: "グループから移動します",
	移动: "移動",
	移动端专用: "モバイルのみ",
	移动端快捷操作: "モバイル端末でのクイック操作",
	移动设备: "モバイルデバイス",
	移除: "削除",
	"移除 {0}": "{0} を削除",
	移除计划: "プランを削除します",
	移除记录: "レコードを削除します",
	"移除进程 ": "プロセスを削除します",
	"空值表示无条件；表达式不满足时，下游会跳过。": "null 値は無条件を意味します。式が満たされない場合、下流はスキップされます。",
	空闲: "待機",
	"窗口（秒）": "ウィンドウ (秒)",
	立即安装: "今すぐインストール",
	端口: "ポート",
	笔记: "メモ",
	笔记关系图: "ノート関係図",
	笔记关联: "ノートの関連付け",
	笔记助手: "ノートアシスタント",
	笔记库: "ノートライブラリ",
	笔记总体关系图: "メモの全体関係図",
	笔记文件树: "ノートファイルツリー",
	笔记来源: "メモのソース",
	笔记节点: "ノートノード",
	第: "いいえ。",
	"第 {0} / {1} 项": "アイテム {0}/{1}",
	"第 {0} 条用户指令，共 {1} 条": "ユーザー コマンド {0}/合計 {1}",
	"第 {0} 条角色分配必须选择建议模型。": "ロール割り当て {0} は提案されたモデルを選択する必要があります。",
	"第 {0} 条角色分配的任务类型不能为空。": "ロール割り当て {0} のタスク タイプを空にすることはできません。",
	"第 {0} 条角色分配的最低思考强度不能高于最高思考强度。": "ロール {0} に割り当てられる最小思考強度は、最大思考強度より高くすることはできません。",
	"第 {0} 行": "行 {0}",
	"第 {0}/{1} 段": "段落 {0}/{1}",
	等待: "待機中",
	等待中: "待機中",
	等待事件: "イベントを待機",
	等待你的选择: "あなたの選択を待っています",
	"等待外部事件后继续执行。": "実行を続行する前に、外部イベントを待ってください。",
	等待选择: "選択を待機しています",
	等待回答: "回答待ち",
	策略: "戦略",
	"策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。": "ポリシーはワークフローの実行に適用されます。制限された実行は再試行可能な一時停止状態になり、実行スロットを占有しません。",
	筛选资料: "リソースを絞り込む",
	筛选资料库: "ライブラリを絞り込む",
	"管理 web_search 工具使用的搜索引擎内核与网络代理，保存到 websearch 插件配置后即时生效。": "web_search ツールによって使用される検索エンジン コアとネットワーク プロキシを管理します。これは、websearch プラグイン構成に保存するとすぐに有効になります。",
	"管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。": "管理イベントフック。信頼できないフックは実行されないため、このレビュー後に有効にする必要があります。",
	管理你的知识: "知識を管理する",
	管理定时任务: "スケジュールされたタスクを管理する",
	"管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。": "検出されたスキルを管理します。無効にすると、スラッシュ コマンドには表示されなくなります。新しいスキルはユーザーレベルのスキルディレクトリに書き込まれ、エージェントはオンデマンドでload_skillを呼び出します。",
	"管理已安装的插件，开关它们带来的界面与工具。": "インストールされているプラ​​グインを管理し、プラグインが提供するインターフェイスとツールを切り替えます。",
	"管理模型接入、供应商配置与默认模型选择。": "モデルへのアクセス、サプライヤー構成、およびデフォルトのモデル選択を管理します。",
	管理目标: "管理対象",
	类型: "タイプ",
	"类型 {0}": "{0} と入力します",
	粉色: "ピンク",
	粘贴: "貼り付け",
	"粘贴失败：当前环境无法读取剪贴板": "貼り付けに失敗しました: 現在の環境ではクリップボードを読み取ることができません",
	系统: "システム",
	系统打开: "システムがオープンしました",
	"系统提示词…": "システム プロンプト ワード...",
	索引可用: "インデックスが利用可能です",
	索引异常: "インデックス例外",
	索引未检查: "インデックスがチェックされていません",
	紧凑: "コンパクト",
	紫色: "紫",
	紫蓝渐变: "紫と青のグラデーション",
	红色: "赤",
	纯文本: "プレーンテキスト",
	"纯色层级更安静，并以清晰实线边界维持长期工作的可读性。": "単色レベルは静かで、明確な実線の境界線で長期作業でも可読性を維持します。",
	纵向分布: "垂直分布",
	终止进程: "プロセスを終了します",
	"终止进程 ": "プロセスを終了します",
	"终止这个回合？": "このターンを終了しますか？",
	结束: "終了",
	结果: "結果",
	"结果上限 limit（默认 5，1-20）": "結果の上限値 (デフォルトは 5、1 ~ 20)",
	结论: "結論",
	"给 Sunday 发送任务...": "タスクを日曜日に送信します...",
	"继承全局策略：{0}": "グローバル ポリシーの継承: {0}",
	"继承全局（当前：{0}）": "グローバルの継承 (現在: {0})",
	继续编辑: "編集を続行します",
	"继续问…": "質問を続けてください...",
	绿色: "緑",
	缓存: "キャッシュ",
	缓存命中率: "キャッシュヒット率",
	"缓存（": "キャッシュ (",
	编排: "オーケストレーション",
	编辑: "編集",
	"编辑 {0}": "{0}を編集します",
	编辑供应商: "サプライヤーの編集",
	编辑右侧面板布局: "右パネルのレイアウトを編集",
	编辑定时任务: "スケジュールされたタスクを編集する",
	编辑工作流: "ワークフローの編集",
	编辑待发送内容: "送信するコンテンツを編集します",
	编辑文件: "ファイルを編集",
	编辑条件: "条件の編集",
	编辑模型: "モデルの編集",
	编辑消息: "メッセージを編集",
	编辑笔记全文: "メモの全文を編集します",
	编辑节点: "ノードの編集",
	编辑连线条件: "接続条件の編集",
	缩小: "ズームアウト",
	缺少可打开的附件标识: "開くことができる添付ファイルの識別子がありません",
	缺少可读取的文本路径: "読み取り可能なテキストパスがありません",
	网关: "ゲートウェイ",
	网关运行中: "ゲートウェイが実行中です",
	网格吸附已关闭: "グリッド スナップがオフになっています",
	网格吸附已开启: "グリッドスナップがオンになっています",
	网格视图: "グリッドビュー",
	置顶: "ピン留め",
	置顶会话: "固定された会話",
	置顶项目: "ピン留めされたアイテム",
	翻译: "翻訳",
	耗时: "時間がかかる",
	"耗时 ": "時間がかかる",
	"耗时 {0} s": "{0} 秒かかりました",
	"耗时 —": "時間がかかる —",
	聊天: "チャット",
	聚焦选中: "フォーカスが選択されました",
	"背景板 / 侧边栏": "背景/サイドバー",
	能力: "アビリティ",
	能力分类: "能力分類",
	"能力的模型。保存到": "機能のモデル。に保存する",
	自动: "自動",
	自动检查: "自動チェック",
	"自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。": "自動モードでは、使用可能なシェルが WSL → Git Bash → PowerShell の順序で選択されます。手動で選択したシェルが使用できない場合も、この順序でフォールバックします。",
	"自动继续的内存阈值（GB）": "自動続行のメモリしきい値 (GB)",
	"自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。": "自動継続のメモリしきい値 (GB): 利用可能なメモリ = 物理メモリ + ページ ファイルがまだ割り当てることができる量。上げるとより控えめになりますが、時間がかかります。",
	"自动（内置声明）": "自動 (組み込み宣言)",
	自定义: "カスタム",
	"自定义工作流节点。": "カスタム ワークフロー ノード。",
	自定义接口: "カスタムインターフェイス",
	自定义证书: "カスタム証明書",
	自检: "セルフテスト",
	"自迭代 (loop)": "自己反復 (ループ)",
	节流: "スロットリング",
	"节流 {0}s": "{0} をスロットリングしています",
	节点: "ノード",
	"节点 {0} · 画布元素 {1}": "ノード {0} · キャンバス要素 {1}",
	节点分类: "ノードの分類",
	节点参数: "ノードパラメータ",
	节点已对齐: "ノードが整列しています",
	节点已横向分布: "ノードは水平に分散されています",
	节点已纵向分布: "ノードは垂直に分散されています",
	节点标题: "ノードのタイトル",
	节点目录: "ノードディレクトリ",
	节点目录筛选: "ノード ディレクトリのフィルタリング",
	"英 {0} 美 {1}": "英国 {0} 米国 {1}",
	"范围 {0}-{1} 行": "範囲 {0}-{1} 行",
	"范围进度，尚未独立评估": "スコープの進行状況、独立して評価されていません",
	草稿: "ドラフト",
	莓果渐变: "ベリーグラデーション",
	"莓紫、灰蓝与青绿的横向渐变。": "ラズベリーパープル、グレーブルー、ターコイズ色の水平グラデーション。",
	获取网页: "Web ページの取得",
	"获取网页 {0}": "Web ページ {0} を取得します",
	蓝色: "青",
	行: "OK",
	行内代码: "インラインコード",
	"补齐缺少的端口（": "不足しているポートが完了しました (",
	表单说明: "フォームの説明",
	表格: "テーブル",
	覆盖: "上書き",
	"规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。": "ルールは、サブエージェントが規律を呼び出した後に均一に追加されます。タスク タイプが一致すると、メイン エージェントには、推奨されるサブエージェント タイプ、モデル、および思考強度の範囲が提供されます。",
	视图切换: "ビューの切り替え",
	视觉: "ビジョン",
	角色: "役割",
	角色分配: "役割の割り当て",
	解释: "説明",
	解锁: "ロックを解除する",
	"解锁 {0}": "{0}のロックを解除します",
	触发器: "トリガー",
	"触发器 ID 不能为空": "トリガー ID を空にすることはできません",
	"触发器 ID 已存在：{0}": "トリガー ID はすでに存在します: {0}",
	"触发器 {0}": "トリガー {0}",
	触发器列表: "トリガーリスト",
	"触发器已保存。": "トリガーが保存されました。",
	触发器激活: "トリガーがアクティブになりました",
	触发器类型: "トリガーの種類",
	计划: "計画中",
	计划更新失败: "スケジュールされた更新に失敗しました",
	"计划：{0} 步": "計画: {0} ステップ",
	"让 agent 完成的目标…": "エージェントに目標を完了させます...",
	记忆: "メモリ",
	记忆名称: "メモリ名",
	"记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。": "メモリは単なる普通のファイルです。ここに書き込んだ内容は、その後のすべてのセッションでアシスタントによって読み取られます。",
	记忆档位: "メモリーギア",
	记忆续跑: "メモリ継続",
	记忆编辑: "メモリ編集",
	记忆阅读: "メモリ読み取り",
	设为预设首选: "デフォルト設定として設定",
	设备: "デバイス",
	"设备 ID": "デバイスID",
	设备与工作环境: "設備と作業環境",
	设置: "設定",
	设置分区: "パーティションの設定",
	"设置界面语言、网络连接与运行偏好。": "表示言語、ネットワーク接続、動作設定を変更します。",
	设计创作: "デザイン作成",
	询问: "確認する",
	该供应商下还没有模型: "このサプライヤーにはまだモデルがありません",
	该目录已在列表中: "ディレクトリはすでにリストにあります",
	该组还没有模型: "このグループにはまだモデルがありません",
	该连线已经存在: "接続はすでに存在します",
	详情: "詳細",
	详细调整: "詳細な調整",
	"说明何时使用，供 Agent 检索": "エージェントが取得するためにいつ使用するかを示します",
	"说明希望如何处理…": "処理方法を指定してください...",
	"请先保存工作流并解决冲突，再激活触发器": "トリガーをアクティブ化する前に、ワークフローを保存して競合を解決してください。",
	"请先新增供应商，再添加模型": "最初にサプライヤーを追加してからモデルを追加してください",
	"请先添加供应商/模型（设置 → 模型与供应商）": "最初にプロバイダーとモデルを追加してください（設定 → モデル）。",
	请先选择会话: "最初にセッションを選択してください",
	请先选择供应商: "最初にサプライヤーを選択してください",
	"请填写必填输入：{0}": "必須の入力を行ってください: {0}",
	请求中: "リクエスト中",
	"请输入有效 JSON：{0}": "有効な JSON を入力してください: {0}",
	"请选择完整归档的保存位置…": "完全なアーカイブを保存する場所を選択してください...",
	读: "読み取り",
	"读取 {0}": "{0}を読み取り中",
	读取中: "読み取り中",
	"读取中…": "読み取り中...",
	"读取了{0}个文件": "{0} ファイルが読み取られました",
	"读取了{0}个文件…": "{0} 個のファイルが読み取られました...",
	读取失败: "読み取りに失敗しました",
	读取定时任务失败: "スケジュールされたタスクの読み取りに失敗しました",
	读取文件: "ファイルを読み取り中",
	"读取运行记录…": "実行記録を読み取り中...",
	"读取运行详情失败：{0}": "実行の詳細を読み取れませんでした: {0}",
	调度: "スケジュール設定",
	调度方式: "スケジュール方法",
	调整主界面: "メインインターフェイスを調整する",
	"调整内容区的信息密度。": "コンテンツ領域の情報密度を調整します。",
	调整子代理面板宽度: "サブエージェントパネルの幅を調整する",
	调整宽高: "幅と高さを調整する",
	调整控件: "コントロールを調整する",
	"调整此任务的执行时间、指令和运行方式。": "このタスクの実行時間、命令、および実行モードを調整します。",
	调整背景板和侧边栏: "背景パネルとサイドバーを調整する",
	调整输入栏: "入力フィールドを調整する",
	调用: "電話をかける",
	"调用 MCP 工具": "MCP ツールを呼び出す",
	"调用一次 (none)": "1 回呼び出されました (なし)",
	"调用了{0}个工具": "{0} ツールが呼び出されました",
	"调用另一个工作流。": "別のワークフローを呼び出しています。",
	"调用智能体执行任务，可按需使用工具。": "エージェントを呼び出してタスクを実行し、必要に応じてツールを使用します。",
	"象牙白与石墨灰的纯色主题。": "アイボリーホワイトとグラファイトグレーのソリッドカラーテーマ。",
	负责人: "担当者",
	"负责逐工具能力边界，不在这里重复配置。": "ツール機能の境界を定義する責任を負い、ここでは構成を繰り返しません。",
	账号: "アカウント",
	账号与设备: "アカウントとデバイス",
	"账号绑定命令将在桌面 Tauri 运行时启用。": "アカウント バインディング コマンドは、デスクトップ Tauri の実行中に有効になります。",
	资料: "リソース",
	"资料 / 记忆 / 方案 — 一个入口三块内容。": "リソース / メモリ / プラン — 3 つのセクションを 1 か所に。",
	资料库: "ライブラリ",
	"资料库 › {0}": "ライブラリ › {0}",
	"资料库 › 资料": "ライブラリ › リソース",
	资料库分区: "ライブラリのセクション",
	资料库还是空的: "ライブラリはまだ空です",
	资源: "リソース",
	超时: "タイムアウト",
	"超时 ": "タイムアウト",
	"超时 (秒)": "タイムアウト (秒)",
	"超时秒数 timeout": "タイムアウト秒タイムアウト",
	"超时（秒）": "タイムアウト (秒)",
	超高: "非常に高い",
	跟随系统: "システムに従ってください",
	"跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。": "プロジェクト間で共有されるメモリ — モデルはセッションでメモリを読み取り、ここで整理します。",
	"跨项目查找会话、消息、方案与文件。": "プロジェクト全体でセッション、メッセージ、プロジェクト、およびファイルを検索します。",
	路径: "パス",
	跳过: "スキップ",
	转到注册: "登録に移動",
	转换: "変換",
	"转换（兼容）": "変換(互換)",
	轻: "低",
	输入: "入力",
	"输入你的回答…": "答えを入力してください...",
	"输入关键词搜索任务、插件或文件": "キーワードを入力してタスク、プラグイン、またはファイルを検索します",
	"输入内容...": "コンテンツを入力してください...",
	"输入内容…": "コンテンツを入力してください...",
	"输入必须是对象：{0}": "入力はオブジェクトである必要があります: {0}",
	"输入必须是数字：{0}": "入力は数値である必要があります: {0}",
	"输入必须是数组：{0}": "入力は配列である必要があります: {0}",
	输入栏: "入力フィールド",
	"输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。": "入力ボックスの「Ask/Auto/Full Access」は、現在のセッションのリアルタイムのステータスです。自動アクセスまたはフルアクセスに切り替えると、保留中の承認操作がすぐに解除されます。",
	输入端口: "入力ポート",
	输入端口类型: "入力ポートの種類",
	输入输出: "入力と出力",
	输出: "出力",
	"输出工作流结果。": "ワークフロー結果を出力します。",
	"输出格式（文本说明，可选）": "出力形式 (テキスト説明、オプション)",
	输出端口: "出力ポート",
	"输出端口 = JSON 字段（强制 JSON 输出）": "出力ポート = JSON フィールド (強制的に JSON 出力)",
	"输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）": "出力ポート = JSON キー名 (標準出力が JSON の場合は自動的に分割されます)",
	"输出端口 = 给同名变量赋值": "出力ポート = 同じ名前の変数に値を代入します",
	输出端口类型: "出力ポートの種類",
	"输出预设的常量值。": "あらかじめ設定されている定数値を出力します。",
	过程: "プロセス",
	过程图标颜色: "プロセスアイコンの色",
	过程图标颜色十六进制值: "プロセスアイコンの色の 16 進値",
	运行: "実行",
	"运行 ID": "実行ID",
	"运行 {0}": "{0} を実行中",
	"运行一条 Shell 命令。": "シェルコマンドを実行します。",
	运行与适配: "操作と適応",
	运行中: "実行中",
	"运行中…": "実行中...",
	运行事件: "実行中のイベント",
	运行历史: "実行履歴",
	运行命令: "コマンドを実行",
	运行失败: "実行に失敗しました",
	"运行失败：{0}": "実行に失敗しました: {0}",
	运行整个工作流: "ワークフロー全体を実行する",
	运行时: "ランタイム",
	运行模式: "実行モード",
	运行模式与权限参数: "実行モードと権限パラメータ",
	"运行模式与权限：{0} · {1}": "実行モードと権限: {0} · {1}",
	运行模式选项: "実行モードのオプション",
	运行此节点: "このノードを実行しています",
	运行状态: "運転状況",
	运行策略: "ポリシーの実行",
	运行结果: "実行結果",
	"运行节点…": "ノードを実行中...",
	运行详情: "操作の詳細",
	运行输入: "入力を実行",
	"运行输入必须是 JSON 对象": "実行入力は JSON オブジェクトである必要があります",
	"运行输入（JSON，可选）": "実行入力 (JSON、オプション)",
	运行进度: "実行の進行状況",
	运行链路: "リンクを実行中",
	返回: "戻る",
	返回主会话: "メインセッションに戻る",
	返回主界面: "メイン画面に戻る",
	返回会话: "セッションに戻る",
	"返回会话（Esc）": "セッションに戻る (Esc)",
	返回列表: "リストに戻る",
	返回学习: "勉強に戻る",
	返回对话: "会話に戻る",
	返回登录: "ログインに戻る",
	还原: "復元",
	"还没有 Markdown 笔记。": "Markdown ノートはまだありません。",
	还没有供应商: "サプライヤーがまだありません",
	"还没有内容。": "まだコンテンツがありません。",
	还没有定时任务: "スケジュールされたタスクはまだありません",
	还没有工作模式: "まだ動作モードがありません",
	"还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。": "まだアーカイブされていません - ファイル カードのメニューの「フォルダーにアーカイブ」がここに表示されます。",
	"还没有摘要 — 打开写第一段。": "まだ要約がありません - 最初の段落を書くために開いています。",
	"还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。": "お気に入りのソリューションがまだありません - ソリューション カードのメニューに [お気に入りに追加] があります。",
	还没有方案: "まだ計画はありません",
	还没有模型组: "モデル グループがまだありません",
	还没有运行历史: "実行履歴がまだありません",
	"还没有运行记录。": "実行記録がまだありません。",
	还没有项目有记忆: "まだメモリを持っているプロジェクトはありません",
	这一层还没有文件: "このレイヤーにはまだファイルがありません",
	这一行没有可打开的文件路径: "この行には開くことができるファイル パスがありません",
	"这个子代理还没有产生过程记录。": "このサブエージェントはプロセス レコードを生成していません。",
	这个文件夹还是空的: "このフォルダーはまだ空です",
	"这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。": "このフォルダーはまだ空です。右上隅の [新しいソリューション] をクリックすると、ここに作成されます。",
	"这个文件夹里还没有记忆文件。": "このフォルダーにはまだメモリ ファイルがありません。",
	这个模式可以使用全部工具: "このモードではすべてのツールを使用できます",
	"这个状态下暂无任务。": "この状態のタスクはありません。",
	"这个状态下暂无方案。": "この状態では解決策はありません。",
	"这个账号还没有已登记设备。": "このアカウントには登録されたデバイスがありません。",
	"这些信息用于连接模型服务。": "この情報は、モデル サービスに接続するために使用されます。",
	"这些设置只作为新会话的起点，不会静默改变已经运行的任务。": "これらの設定は、新しいセッションの開始点としてのみ機能し、すでに実行中のタスクを暗黙的に変更するものではありません。",
	这条消息没有可用的回合: "このメッセージに使用できるラウンドはありません",
	"这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。": "この参照はドキュメント内に複数回出現するため、安全にロックできません。編集モードで選択してください。",
	这片记忆还是空的: "このメモリはまだ空です",
	"这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。": "ここに表示するナレッジ ポイントはまだありません。まず学習セッションで AI に知識ネットワークを構築させます。",
	这里还没有子文件夹: "ここにはまだサブフォルダーがありません",
	进度: "進行状況",
	进程日志: "プロセスログ",
	进行中: "進行中です",
	进阶: "高度な",
	"远程图片仅在 Study 中显示：{0}": "リモート画像は Study でのみ表示されます：{0}",
	"远端工作流有更新，请处理冲突": "リモート ワークフローが更新されました。競合を処理してください。",
	"连接一个可用的模型服务。": "利用可能なモデル サービスに接続します。",
	连接信息: "接続情報",
	连接异常: "接続例外",
	连线已更新: "接続が更新されました",
	迭代模式: "反復モード",
	"追加加载的文件（addition）": "追加ロードファイル(追加)",
	退出条件: "終了条件",
	"退出条件（Python 表达式）": "終了条件 (Python 式)",
	"退出码 ": "終了コード",
	"退出码 {0}": "終了コード {0}",
	退出账号: "アカウントからログアウトします",
	"适合长时间处理任务与配置。": "長期的な処理タスクおよび構成に適しています。",
	适应画布: "キャンバスに合わせる",
	"选中文字后右键，即可解释、询问或翻译。": "説明、質問、または翻訳するテキストを選択した後、右クリックします。",
	选填: "オプション",
	"选填，如限速、用途、注意事项等": "速度制限、目的、注意事項などのオプション。",
	"选填，留空时使用模型 ID": "オプション、空白のままの場合はモデル ID を使用します",
	选择: "選択",
	"选择 {0}": "{0}を選択してください",
	"选择一个工作目录，系统会为项目准备基础配置。": "作業ディレクトリを選択すると、システムはプロジェクトの基本構成を準備します。",
	"选择一个已登记的项目继续工作。": "作業を続行するには、登録済みプロジェクトを選択します。",
	"选择主题随系统变化、固定在一个模式，或按时段自动切换。": "システムに合わせて変更するテーマ、モードに固定するテーマ、または期間に応じて自動的に切り替えるテーマを選択します。",
	选择供应商: "サプライヤーを選択してください",
	"选择官方模板，或手动填写服务信息。": "公式テンプレートを選択するか、サービス情報を手動で入力します。",
	选择工作模式: "動作モードの選択",
	"选择工作流 JSON 文件": "ワークフロー JSON ファイルを選択してください",
	选择工作环境: "作業環境の選択",
	选择已有照片: "既存の写真を選択してください",
	选择已登记项目: "登録済み項目を選択",
	"选择应用界面的显示语言。不会更改对话内容或模型的回答语言。": "アプリの表示言語を選択します。会話内容やモデルの回答言語は変更されません。",
	选择或填写项目地址: "プロジェクトのアドレスを選択または入力します",
	"选择或输入模型 ID": "モデル ID を選択または入力してください",
	选择模型: "モデルの選択",
	选择模型组: "モデルグループの選択",
	"选择模板后，按官方页面申请 API key；免费模型通常有额度或容量限制。": "テンプレートを選択した後、公式ページから API キーを申請します。無料モデルには通常、クォータまたは容量制限があります。",
	选择此目录: "このディレクトリを選択してください",
	选择目录: "ディレクトリを選択してください",
	选择要放入: "選択して配置します",
	选择附件来源: "添付ファイルのソースを選択してください",
	选择项目: "項目を選択してください",
	"选择项目后查看成果库。": "プロジェクトを選択した後、結果ライブラリを表示します。",
	选择项目目录: "プロジェクト ディレクトリを選択してください",
	透明度: "透明性",
	"逐工具白名单、工具模式与扩展权限分别管理": "ツールのホワイトリスト、ツール モード、拡張権限を個別に管理する",
	通用: "一般",
	通用文件夹: "ユニバーサルフォルダー",
	通过对话创建笔记: "会話からメモを作成する",
	速率限制: "レート制限",
	"遍历数组 (map)": "配列 (マップ) をトラバースします",
	配图: "イラスト",
	配对新设备: "新しいデバイスのペアリング",
	配置: "構成",
	"配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。": "sub_agent のコール プロンプト ワードを設定して、メイン エージェントにサブエージェント (モデル/モードなど) をいつどのように委任するかを指示します。",
	"配置任务的执行时间、指令和运行方式。": "タスクの実行時間、命令、および実行モードを構成します。",
	配置完成: "構成が完了しました",
	配置文件: "構成ファイル",
	配置模型供应商: "モデルプロバイダーを構成する",
	采用远端版本: "リモート バージョンを使用する",
	重做: "やり直し",
	"重做（Ctrl/Cmd+Shift+Z）": "やり直し (Ctrl/Cmd+Shift+Z)",
	重合区域: "重複領域",
	"重合区域：": "重複領域:",
	重命名: "名前を変更",
	"重命名会话 {0}": "セッション {0} の名前を変更します",
	"重命名失败：{0}": "名前の変更に失敗しました: {0}",
	重命名方案: "スキームの名前を変更します",
	重命名模型组: "モデルグループの名前を変更します",
	重新下载: "再ダウンロード",
	重新显示首次引导: "最初のブートを再表示する",
	重新检查: "再確認",
	重试: "再試行してください",
	重试中: "再試行中",
	"重试中 {0}/{1}": "{0}/{1} を再試行しています",
	重试次数: "再試行回数",
	重连中: "再接続中",
	钩子: "フック",
	钩子·已信任: "フック・信頼済み",
	链接: "リンク",
	锁定选中内容: "ロック選択",
	错误处理: "エラー処理",
	错误输出: "エラー出力",
	"长期驻留（轮次结束后继续运行）": "長期滞在(ラウンド終了後も走り続ける)",
	问题: "問題",
	间隔: "間隔",
	间隔秒数: "間隔秒",
	"间隔触发器需要 every_seconds": "間隔トリガーにはevery_秒が必要です",
	"阈值需要是 0.5 到 1024 之间的数字（GB）": "しきい値は 0.5 ~ 1024 (GB) の数値である必要があります",
	"队列 ID": "キューID",
	队列与历史: "キューと履歴",
	队列优先级: "キューの優先順位",
	"队列刷新失败：{0}": "キューの更新に失敗しました: {0}",
	队列视图: "キュービュー",
	队列运行详情: "キュー操作の詳細",
	防抖: "手ぶれ補正",
	"防抖 {0}s": "手ぶれ補正 {0}",
	防抖模式: "手ぶれ補正モード",
	附件: "添付ファイル",
	"附件上传失败：{0}": "添付ファイルのアップロードに失敗しました: {0}",
	附件预览失败: "添付ファイルのプレビューに失敗しました",
	附件预览已读取: "添付ファイルのプレビューが読み込まれました",
	降级输出: "ダウングレードされた出力",
	降级输出端口: "出力ポートをダウングレードします",
	降级默认值: "デフォルトをダウングレードします",
	"限速 {0}/{1}s": "速度制限 {0}/{1} 秒",
	随轮次结束清理: "ラウンド終了時のクリーンアップ",
	隐藏已移除: "非表示が削除されました",
	"雾蓝到奶油白的浅色渐变。": "霧の青からクリーム色の白までの光のグラデーション。",
	需压缩: "圧縮が必要です",
	需确认: "確認が必要です",
	需要你确认: "確認が必要です",
	"需要你确认，共 {0} 项": "確認が必要です、合計 {0} 個のアイテム",
	青色: "シアン",
	面板: "パネル",
	音视频: "オーディオとビデオ",
	顶对齐: "上揃え",
	项: "アイテム",
	项目: "プロジェクト",
	"项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。": "プロジェクト スコープの sub_agent 構成はグローバル構成をオーバーライドします。継承されたグローバル/組み込みのデフォルトにフォールバックするには、空白のままにします。",
	"项目作用域的元信息与 AGENTS.md 指令。": "AGENTS.md ディレクティブを使用したプロジェクト スコープのメタ情報。",
	"项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。": "プロジェクトは作業ディレクトリ、セッション、および実行構成を保存します。使用したディレクトリを開くこともできます。",
	"项目列表不可用，无法进入项目记忆": "プロジェクト リストが利用できません。プロジェクト メモリを入力できません。",
	项目名称: "プロジェクト名",
	项目图标: "プロジェクトアイコン",
	项目图标与颜色: "プロジェクトのアイコンと色",
	项目地址: "プロジェクトアドレス",
	项目外观: "プロジェクトの外観",
	"项目将保存在当前设备。": "プロジェクトは現在のデバイスに保存されます。",
	"项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。": "プロジェクトはオーバーライドを使用して構成されていません。ポリシーを選択して保存すると、現在のプロジェクトのみが書き込まれます。",
	项目成果库: "プロジェクト結果ライブラリ",
	项目操作: "プロジェクトの操作",
	"项目文件和自动生成的 AGENTS.md 将存放在此目录。": "プロジェクト ファイルと自動生成された AGENTS.md はこのディレクトリに保存されます。",
	项目目录: "プロジェクトディレクトリ",
	项目规则: "プロジェクトルール",
	项目记忆: "プロジェクトメモリ",
	"项目记忆按项目归档 — 先选一个项目，再整理它的记忆。": "プロジェクトの思い出はプロジェクトごとにアーカイブされます。まずプロジェクトを選択してから、その思い出を整理します。",
	项目设置: "プロジェクト設定",
	项目设置分区: "プロジェクト設定パーティション",
	"项目里进出的文件 — 用户上传、中间产物与最终产物。": "プロジェクト内外のファイル - ユーザーのアップロード、中間製品、および最終製品。",
	项目颜色: "アイテムの色",
	"项；文件本身不会被删除。": "アイテム;ファイル自体は削除されません。",
	预览: "プレビュー",
	"预览 {0}": "{0} をプレビュー",
	预览排版: "レイアウトのプレビュー",
	预设颜色: "デフォルトの色",
	预设首选: "デフォルトの設定",
	频率: "周波数",
	颜色: "色",
	"颜色节点、透明度与界面密度": "カラーノード、透明度、インターフェース密度",
	风险扫描: "リスクスキャン",
	首个执行: "最初の実行",
	首次任务: "最初のミッション",
	首次使用引导: "初回起動",
	验证: "検証",
	验证未通过: "認証に失敗しました",
	高: "高",
	"高危命令默认需要运行前确认（自动批准模式除外）。": "高リスクのコマンドは、デフォルトで実行前に確認が必要です (自動承認モードを除く)。",
	高级工具白名单: "高度なツールのホワイトリスト",
	高级设置: "詳細設定",
	高级调整: "高度な調整",
	"高级适配 JSON": "高度な適応 JSON",
	"高级适配 JSON 必须是对象": "Advanced Adaptation JSON はオブジェクトである必要があります",
	默认: "デフォルト",
	"默认值（空=哨兵跳过）": "デフォルト値 (空 = センチネルはスキップ)",
	"默认内核 provider": "デフォルトのカーネルプロバイダー",
	默认多模态解析模型: "デフォルトのマルチモーダル解析モデル",
	"默认审批策略保存失败，已回滚：{0}": "デフォルトの承認ポリシーは保存に失敗し、ロールバックされました: {0}",
	默认搜索内核: "デフォルトの検索カーネル",
	默认模型: "デフォルトのモデル",
	"（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。 外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。": "(国内で到達可能、推奨) · bing (英語/普通分詞が利用可能) · ddg (海外のスペアタイヤ)。外部ツール (GPL/AGPL などの独立したプロセス) は subprocess/http 経由でアクセスされ、JSONC を手動で構成する必要があります。",
	"（支持": "(サポートされています",
	"（无）": "(なし)",
	"（日志为空）": "(ログが空です)",
	"（暂无日志输出）": "(まだログ出力はありません)",
	"（检查网络后重试）": "(ネットワークを確認して再試行してください)",
	"（空指令）": "(空のコマンド)",
	"（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "(統合構成ディレクトリ)。 「プロジェクト設定 → プロジェクト」でプロジェクト レベルのルールを編集してください。この 2 つはシステム プロンプト ワードを挿入するために一緒に追加されます。",
	"（还没有内容）": "(まだコンテンツがありません)",
	"（还没有摘要）": "(概要はまだありません)",
	"（默认 work_root）": "(デフォルトの work_root)",
	"（默认模型）": "(デフォルトモデル)",
	"＋ 新增模型": "+ 新しいモデルを追加",
	"＋ 新建供应商": "+ 新しいサプライヤーを作成",
	"＋ 追加文件": "+ ファイルを追加",
	"，且无法恢复。": "、復元できません。",
	"，但没有适用于本平台的安装包（可到发布页查看）": "ですが、このプラットフォームに適したインストール パッケージがありません (リリース ページで確認できます)",
	"，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：": "、各ワークスペースにグローバルにオーバーレイします (ワークスペース独自のload_context.jsonc がその上にオーバーレイされます)。 CLI:",
	"，移动端为应用私有技能目录）。": "、モバイル端末はアプリケーションのプライベート スキル ディレクトリです)。",
	"，里面的条目也会一起删掉": "、内部のエントリも一緒に削除されます。",
	"：暂无可配置参数": ": 設定パラメータがまだありません",
	"thinking.off": "オフ",
	"保存修改？": "変更を保存しますか？",
	丢弃修改: "変更を破棄",
	"未能保存，请检查修改后重试。": "保存できませんでした。変更内容を確認して再試行してください。",
	自动恢复阈值: "自動再開のしきい値",
	子代理指南: "サブエージェントガイド",
	代理地址: "プロキシアドレス",
	直连地址: "直接接続先",
	"CA 证书": "CA 証明書",
	"请填写必填项并检查输入格式。": "必須項目と入力形式を確認してください。",
	"配置已保存，但未能完成同步：{0}": "設定は保存されましたが、同期を完了できませんでした：{0}",
	继续运行: "実行を再開",
	重试启动: "起動を再試行",
	"新插件系统（预览）": "新しいプラグインシステム（プレビュー）",
	"与当前插件页互不影响。这里只验证清单、启停和卸载。": "現在のプラグインページとは独立しています。ここではマニフェスト、有効化、アンインストールのみを確認します。",
	"还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "プラグインはまだありません。name と version だけを書いた plugin.json をプラグインルートに置くと表示されます。",
	禁用: "無効化",
	没有声明能力: "宣言された機能はありません",
	"声明错误：{0}": "宣言エラー：{0}",
	"加载错误 {0}": "読み込みエラー {0}",
	"卸载 {0}？data 目录会保留。": "{0} をアンインストールしますか？data ディレクトリは保持されます。",
	"已卸载 {0}，data 目录保留。": "{0} をアンインストールしました。data ディレクトリは保持されています。",
	会修改数据: "データを変更します",
	"sha256（可选）": "sha256（任意）",
	"{0} 条匹配": "{0} 件が一致",
	"内核（不可替换）": "カーネル（置き換え不可）",
	"加载配置中…": "設定を読み込み中…",
	压缩包: "ZIP アーカイブ",
	可替换模块: "置き換え可能モジュール",
	"字段 {0} 需要合法的 JSON。": "フィールド {0} は有効な JSON である必要があります。",
	"已保存 {0} 的配置。": "{0} の設定を保存しました。",
	"当前环境没有桌面窗口，插件窗口只能在桌面端打开。": "この環境にはデスクトップウィンドウがないため、プラグインウィンドウはデスクトップ版でのみ開けます。",
	"打开窗口 {0}": "ウィンドウ {0} を開く",
	收起配置: "設定を閉じる",
	"更新（同名替换，data 保留）": "更新（同名置き換え、data は保持）",
	"查行为表：模块名或片段（如 prompt、plugin_system.host）": "ビヘイビア表を検索：モジュール名や断片（例 prompt、plugin_system.host）",
	查询: "検索",
	没有声明依赖: "依存関係の宣言なし",
	"清单、启停、安装、更新与卸载都在这里。": "マニフェスト・有効/無効・インストール・更新・アンインストールはすべてここで行います。",
	"确定执行 {0}？": "{0} を実行しますか？",
	"确定执行 {0}？该操作会修改数据。": "{0} を実行しますか？この操作はデータを変更します。",
	"自定义配置面板加载失败：{0}": "カスタム設定パネルの読み込みに失敗しました：{0}",
	"这个插件没有可配置项。": "このプラグインに設定項目はありません。",
	筛选文档: "ドキュメントを絞り込む",
	"Wiki 目录": "Wiki 目次",
	目录: "目次",
	文档导航: "ドキュメントナビ",
	没有匹配的文档: "一致するドキュメントがありません",
	没有可用的文档: "利用できるドキュメントがありません",
	"data 目录会保留": "data ディレクトリは保持されます",
	"{0} / {1}": "{0} / {1}",
	"{0} 个已启用": "{0} 個が有効",
	"{0} 个插件": "プラグイン {0} 個",
	"{0} 个需要处理": "{0} 個の対応が必要",
	"依赖：{0}": "依存関係：{0}",
	入口: "入口",
	全局: "グローバル",
	"分屏打开 {0}": "{0} を分割画面で開く",
	"卸载 {0}": "{0} をアンインストール",
	"卸载插件？": "プラグインをアンインストールしますか？",
	启动失败: "起動に失敗",
	"启用 {0}": "{0} を有効にする",
	"在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "プラグインのルートに name と version だけを書いた plugin.json を置くと表示されます。",
	声明错误: "宣言エラー",
	复制安装路径: "インストールパスをコピー",
	安全模式已跳过: "セーフモードでスキップ",
	安装或更新插件: "プラグインのインストールまたは更新",
	安装来源: "インストール元",
	安装来源地址: "インストール元のアドレス",
	已停止: "停止済み",
	"已安装 {0}": "{0} をインストールしました",
	"已更新 {0}": "{0} を更新しました",
	"换个关键词，或清除筛选条件。": "別のキーワードを試すか、フィルターを解除してください。",
	"插件代码已更新，重启应用后模块覆盖和全局脚本将生效。": "プラグインコードが更新されました。アプリを再起動するとモジュールの上書きとグローバルスクリプトが有効になります。",
	插件配置: "プラグイン設定",
	"搜索插件、能力或路径": "プラグイン、機能、パスを検索",
	收起安装: "インストールを閉じる",
	"更新会覆盖同名插件，data 目录会保留。": "更新は同名のプラグインを上書きします。data ディレクトリは保持されます。",
	未声明能力: "機能は未宣言",
	"本地目录、压缩包或链接，三种来源共用一条流程。": "ローカルフォルダ、アーカイブ、リンクの 3 つのソースは同じ流れで扱います。",
	查询行为表: "動作テーブルを検索",
	"模块名或片段（如 prompt、plugin_system.host）": "モジュール名または断片（例：prompt、plugin_system.host）",
	正在切换: "切り替え中",
	正在启动: "起動中",
	"没有加载错误。": "読み込みエラーはありません。",
	没有匹配的插件: "一致するプラグインがありません",
	没有描述: "説明なし",
	清除筛选: "フィルターを解除",
	"禁用 {0}": "{0} を無効にする",
	等待启动: "起動待ち",
	筛选插件: "プラグインを絞り込む",
	缺失: "不足",
	行为表查询与加载错误: "動作テーブルの検索と読み込みエラー",
	诊断与行为表: "診断と動作テーブル",
	运行就绪: "実行準備完了",
	还没有插件: "プラグインはまだありません",
	需要处理: "対応が必要",
	"（缺 {0}，可用 pip 安装；不阻止安装）": "（{0} が不足。pip でインストール可能。インストールは継続）",
	自定义配置面板加载失败: "カスタム設定パネルの読み込みに失敗",
	无法加载插件: "プラグインを読み込めません",
	"检查后台连接后再试一次。": "バックエンドの接続を確認して、もう一度お試しください。",
	再试一次: "再試行",
	"QQ robot": "QQ robot",
	插件页面: "Plugins view",
	源代码与许可证: "Source and licenses",
	"当前显示缓存目录；安装时会重新核对 GitHub 最新发布。": "Showing the cached catalog. Installation checks the latest GitHub release again.",
	插件市场: "Plugin market",
	"从 GitHub 安装插件": "Install plugins from GitHub",
	插件能力: "Capabilities",
	"暂时无法获取市场目录，请检查网络后重试。": "The catalog is unavailable. Check your connection and retry.",
	"正在连接插件市场…": "Connecting to the plugin market…",
	版本暂不可用: "Version unavailable",
	"独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。": "Independently released, installed on demand. Network Exploration optimizes downloads when available; packages are verified before installation.",
	视频与字幕检索: "Video and transcript search",
	内容与信息: "Content and information",
	重新连接: "Reconnect",
	每日内容简报: "Daily content digests",
	消息与协作: "Messaging",
	刷B站: "Bilibili",
	"QQ 私聊与群聊": "QQ chats and groups",
	已安装: "Installed",
	"下载并校验中…": "Downloading and verifying…",
	持久会话: "Persistent sessions",
	消息提醒: "Message reminders",
	暂不可用: "Unavailable",
	changed: "changed",
	有新版本: "Update available",
	审批与文件投递: "Approvals and file delivery",
	"插件已安装，可在“已安装”中配置和管理。": "Plugin installed. Configure and manage it under Installed.",
	"把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。": "Connect Sunday to QQ chats and groups with persistent sessions, approval continuation, and file delivery.",
	"读取视频字幕、整理值得看的内容，生成日报并发送提醒。": "Read video transcripts, curate content, generate daily digests, and send reminders.",
	"Assistant 显示": "Assistant 表示",
	"只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。": "表示だけに影響します。吹き出しの有無、自動分割、表示名とアバターを変更できますが、会話履歴・コンテキスト・メッセージプロトコルは変わりません。",
	"Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。": "Assistant の返信に吹き出しを使うか選べます。オンにすると吹き出しで表示し、オフのときは枠なしの本文のままです。",
	使用消息气泡: "吹き出しを使う",
	"自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。": "自動分割は長い返信を段落と見出しで複数の吹き出しに分けます。コードブロック・数式・表は分割しません。オフにすると返信全体が一つの吹き出しになります。",
	自动气泡拆分: "自動吹き出し分割",
	"显示名称：留空时使用默认名称（Assistant）。": "表示名：空欄の場合は既定名（Assistant）を使います。",
	"例如 Sunday": "例：Sunday",
	"头像：上传一张图片并调整裁切；留空时显示名称首字母。": "アバター：画像をアップロードして切り抜きを調整します。空欄の場合は名前の頭文字を表示します。",
	头像: "アバター",
	"例如 https://example.com/avatar.png": "例：https://example.com/avatar.png",
	图层: "レイヤー",
	元素: "要素",
	未分层: "未設定",
	"在「{0}」内": "「{0}」内",
	父层自动: "親レイヤーは自動",
	"父层 z={0}": "親レイヤー z={0}",
	"自动层（按文档顺序，后绘制的在上）": "親レイヤー内の自動サブレイヤー（文書順、後に描画されたものが上）",
	关闭编辑器: "エディタを閉じる",
	收起面板: "パネルを閉じる",
	展开面板: "パネルを開く",
	编辑模式: "編集モード",
	"编辑模式已关闭，界面可正常操作。": "編集モードはオフです。画面は通常どおり操作できます。",
	不保存修改并退出: "保存せずに終了",
	"在界面上点选组件，或从下面选择。": "画面の部品をクリックするか、下から選びます。",
	"正在预览真实界面，修改会立即生效。": "実際の画面をプレビュー中です。変更はすぐ反映されます。",
	属性: "プロパティ",
	"先选择一个组件。": "先に部品を選択してください。",
	"这个组件是业务入口，只能调整外观，不能移动或隐藏。": "この部品は業務の入口です。外観のみ変更でき、移動や非表示はできません。",
	文字颜色: "文字色",
	背景颜色: "背景色",
	"自动（跟随页面）": "自動（ページに従う）",
	锚点: "アンカー",
	横向: "横方向",
	纵向: "縦方向",
	不锚定: "アンカーなし",
	横向锚点: "横方向アンカー",
	纵向锚点: "縦方向アンカー",
	横向距离: "横方向の距離",
	纵向距离: "縦方向の距離",
	"锚点=到父容器某条边的距离，不会小于 0。": "アンカーは親コンテナの辺までの距離で、0 未満にはなりません。",
	自定义颜色: "カスタム色",
	透明: "透明",
	主区域底色: "メイン面の色",
	主区域柔和底色: "メイン面の淡い色",
	应用底色: "アプリ背景色",
	输入区底色: "入力欄の色",
	控件底色: "コントロールの色",
	背景颜色令牌无效: "背景色トークンが無効です",
	圆角: "角丸",
	间距: "間隔",
	字号: "文字サイズ",
	层级: "重なり順",
	"显示/隐藏图层": "レイヤーの表示/非表示",
	"锁定/解锁图层": "レイヤーのロック/解除",
	"第 {0} 层": "{0} 層目",
	显示: "表示",
	清除这个组件的修改: "この部品の変更を消去",
	有未发布修改: "未公開の変更あり",
	已同步: "同期済み",
	发布: "公開",
	受保护: "保護",
	仅外观: "外観のみ",
	可编辑: "編集可",
	"文件不是有效的主题 JSON": "テーマ JSON として無効なファイルです。",
	编辑布局: "レイアウトを編集",
	打开编辑器: "エディタを開く",
	"进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。": "ビジュアルエディタで色・背景・角丸・文字サイズ・重なり順を調整します。変更はすぐプレビューされ、公開時に保存されます。",
	基础样式: "基本スタイル",
	窄于: "次の幅未満",
	按当前宽度加断点: "現在の幅でブレークポイントを追加",
	删除这个断点: "このブレークポイントを削除",
	"正在编辑窄屏覆盖，只影响该宽度以下。": "狭い幅の上書きを編集中です。この幅以下のみに適用されます。",
	"正在编辑这一条，只影响它自己。": "この 1 件のみを編集しています。ほかには影響しません。",
	横向位置: "横位置",
	纵向位置: "縦位置",
	背景素材: "背景画像",
	选择图片: "画像を選ぶ",
	更换图片: "画像を差し替える",
	图片位置: "画像の位置",
	图片缩放: "画像の拡大率",
	拖动九宫格选择图片显示的部分: "グリッドをドラッグして表示部分を選びます",
	"九宫格就是实际显示的部分，拖动可直接改取景。": "グリッドが実際の表示範囲です。ドラッグで構図を変更できます。",
	模板样式: "スタイルテンプレート",
	允许溢出组件: "部品外への表示を許可",
	"图片过大，单张不能超过 1.5MB": "画像が大きすぎます。1 枚 1.5MB 以下にしてください",
	图片读取失败: "画像の読み込みに失敗しました",
	对齐与分布: "整列と分布",
	右对齐: "右揃え",
	垂直居中: "垂直中央",
	底对齐: "下揃え",
	水平分布: "水平分布",
	垂直分布: "垂直分布",
	top: "上",
	right: "右",
	bottom: "下",
	left: "左",
	上: "上",
	右: "右",
	下: "下",
	左: "左",
	颜色样式: "カラースタイル",
	纯色: "単色",
	渐变: "グラデーション",
	玻璃: "ガラス",
	高透: "高透過",
	低透: "低透過",
	高透玻璃: "高透過ガラス",
	低透玻璃: "低透過ガラス",
	玻璃样式: "ガラススタイル",
	"整个区域换成现成玻璃材质，不再单独调色。": "領域全体を既存のガラス素材に置き換えます。個別の色調整はありません。",
	适应方式: "表示方法",
	铺满: "全体を覆う",
	完整显示: "全体を表示",
	平铺: "タイル",
	拉伸: "引き伸ばし",
	"支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。": "PNG、JPEG、GIF、WebP、AVIF、SVG に対応。アニメーション画像もそのまま再生されます。",
	实验性功能: "実験的機能",
	实验性: "実験的",
	"分屏文件预览（实验性）": "分割ファイルプレビュー（実験的）",
	"图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。": "画像・音声・動画・PDF・Office・Markdown ファイルを内蔵の分割ペインで直接開きます。まだ調整中のため、表示に問題がある場合はオフにして既定のアプリで開いてください。",
	玻璃材质: "ガラス素材",
	"开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。": "オンにすると領域全体がガラス表面になり、上の色・グラデーション・画像がその着色になります。",
	底色: "下地の色",
	上传图片: "画像をアップロード",
	缩放: "ズーム",
	请选择图片文件: "画像ファイルを選択してください",
	"图片不能超过 12 MB": "画像は 12 MB 以下にしてください",
	"图片读取失败，请换一张再试": "画像を読み込めませんでした。別の画像をお試しください",
	"这张图片打不开，请换一张再试": "この画像を開けませんでした。別の画像をお試しください",
	"无法处理这张图片，请换一张再试": "この画像を処理できませんでした。別の画像をお試しください",
	拖动图片调整裁切位置: "画像をドラッグして切り抜き位置を調整",
	"拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。": "画像をドラッグして位置を調整し、スライダーでズームします。円の内側がアバターとして実際に表示される部分です。",
	头像大小: "アバターサイズ",
	圆角率: "角丸率",
	分组名称: "グループ名",
	"删除分组 {0}": "グループ「{0}」を削除",
	"删除分组？": "グループを削除しますか？",
	所属分组: "所属グループ",
	按分组筛选: "グループで絞り込み",
	新建分组: "グループを作成",
	核心: "コア",
	移动到分组: "グループへ移動",
	管理分组: "グループを管理",
	"还没有分组。新建一个，把技能归类到瀑布流的各个分区。": "グループはまだありません。作成してスキルを分類しましょう。",
	"这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。": "このグループにはスキルがありません。カード下のメニューから移動できます。",
	重命名分组: "グループ名を変更",
	按事件筛选: "イベントで絞り込み",
	"这个事件下没有 Hook。切回「全部」看看其他事件。": "このイベントには Hook がありません。「すべて」に切り替えて確認してください。",
	"会话「{0}」已完成，点击打开": "セッション「{0}」が完了しました。クリックで開く",
	"会话「{0}」执行失败，点击打开": "セッション「{0}」が失敗しました。クリックで開く",
	打开会话: "セッションを開く",
	桌宠: "デスクトップペット",
	"展开其余 {0} 项": "残り {0} 件を表示",
	部分文件不存在: "一部のファイルが見つかりません",
	"调用 {0} 次": "{0} 回呼び出し",
	尚未调用: "まだ使われていません",
	"总调用 {0} 次": "合計 {0} 回呼び出し"
}, vu = {
	交互内容: "Interactive content",
	查看代码: "View source",
	"交互内容运行失败，可查看代码或重试": "Interactive content failed. View the source or retry.",
	"交互内容过大，请缩小后重试": "Interactive content is too large. Reduce its size and retry.",
	"交互内容未能加载，可查看代码或重试": "Interactive content could not load. View the source or retry.",
	成稿: "Draft",
	编辑成稿: "Edit draft",
	说明: "Note",
	信息: "Information",
	提示: "Tip",
	注意: "Attention",
	警告: "Warning",
	" · 依赖保留": "· Dependencies retained",
	" · 待审核 {0}": "· Pending review {0}",
	" 个": " items",
	" 个记录": "records",
	" 分组": "Grouping",
	" 子代理时间线": "Subagent Timeline",
	" 时间线": "Timeline",
	" 条": " entries",
	" 的记录": "Records of",
	" 输入框": "Input box",
	"# Sub-agent 委派指南\n在此编写自然语言指令，将注入到主 Agent 系统提示词中…": "# Sub-agent Delegation Guide Write natural language instructions here that will be injected into the main Agent system prompt word...",
	"# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…": "# Global constraints are directives that are effective for all projects. The project-level AGENTS.md will be overlaid on top of this...",
	"# 输入：{0}": "# Input: {0}",
	"# 输出：{0}": "# Output: {0}",
	"# 项目级约束\n项目专属指令，会叠加在全局约束之上…": "# Project-level constraints Project-specific instructions will be superimposed on global constraints...",
	"(项目根)": "(project root)",
	"* 或工具名，多个用 | 分隔": "* or tool name, multiple separated by |",
	"+ 添加节点": "+ Add node",
	"+ 添加输入": "+ Add input",
	"+ 添加输出": "+ Add output",
	"+ 输入端口": "+ input port",
	"+ 输出端口": "+ output port",
	"AGENTS.md · 移动端全局规则": "AGENTS.md · Mobile global rules",
	"AGENTS.md 内容": "AGENTS.md content",
	"AGENTS.md 已保存": "AGENTS.md saved",
	"AI 创意": "AI Creativity",
	"AI 模式": "AI mode",
	"AI（兼容）": "AI (compatible)",
	"API 地址": "API address",
	"API 基础 URL": "API base URL",
	"API 基础 URL 必须与所选供应商一致": "API base URL must match the selected provider",
	"API 配置": "API configuration",
	"Agent 保护区域": "Agent protection area",
	"Agent 工具": "Agent tool",
	"Agent 生成": "Agent generation",
	"Agent 锁定了这段内容": "Agent has locked this content",
	"Core App Server 连接失败": "Core App Server connection failed",
	"DuckDuckGo 本地代理端口": "DuckDuckGo local proxy port",
	"DuckDuckGo 本地代理端口（可选）": "DuckDuckGo local proxy port (optional)",
	"Enter 续列表 · Tab 缩进": "Enter to continue the list · Tab to indent",
	"GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。": "GPL/AGPL components run as independent processes, and the repository does not carry code; LamTools is only called according to a fixed JSON contract (see docs/web-search-module.md for details).",
	"HTTP 代理": "HTTP proxy",
	"ISO 时间": "ISO time",
	"JSON 文件与模板": "JSON files and templates",
	"Linux 直接运行本机命令，不提供 Windows shell 选择。": "Linux runs native commands directly and does not provide a Windows shell option.",
	"MCP 工具名": "MCP tool name",
	"MCP 工具名不能为空": "MCP tool name cannot be empty",
	"Markdown 笔记工作区": "Markdown note workspace",
	"Python 脚本": "Python script",
	"Python 脚本（兼容）": "Python script (compatible)",
	"Python 表达式": "Python expressions",
	"RAG 不可用": "RAG not available",
	"SKILL.md 正文，加载后应遵循的指引": "SKILL.md text, guidelines to be followed after loading",
	"Study 未启用": "Study is not enabled",
	"Sub Agent 思考模式": "Sub Agent thinking mode",
	"Sub Agent 模型": "Sub Agent Model",
	"Sunday 工作区": "Sunday workspace",
	"Sunday 设置": "Sunday settings",
	"URL 不能为空": "URL cannot be empty",
	"Web Search 引擎": "Web Search Engine",
	"[…截断，仅显示尾部…]\n": "[...truncated, only the tail is shown...]",
	"^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$": "^Sub-agent\\s+(.+?)\\s+({0})\\s*[::]\\s*([\\s\\S]+)$",
	"^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$": "^Sub-agent\\s+(.+?)\\s+({0})\\s*. ?\\s*$",
	"at（ISO 时间）": "at (ISO time)",
	"baidu（百度，国内可达）": "baidu (Baidu, reachable in China)",
	"bing（必应中文）": "bing (Bing Chinese)",
	"command (Shell 命令)": "command (Shell command)",
	"command 不能为空": "command cannot be empty",
	"ddg（DuckDuckGo，海外）": "ddg (DuckDuckGo, overseas)",
	"hook 失败时阻断执行": "Block execution when hook fails",
	"hooks.json 内容": "hooks.json content",
	"hooks.json 当前无法解析（不是合法 JSON），已取消保存。请先到「原始配置」视图修复后再添加 Hook。": "hooks.json currently cannot be parsed (not a legal JSON) and has been canceled. Please go to the \"Original Configuration\" view to repair and then add Hook.",
	"http (HTTP 请求)": "http (HTTP request)",
	"load_context.jsonc · 移动端全局加载规则": "load_context.jsonc · Mobile terminal global loading rules",
	"mcp (MCP 工具)": "mcp (MCP tool)",
	"prompt (内联提示)": "prompt (inline prompt)",
	"websearch.jsonc 内容": "websearch.jsonc content",
	"y = x * 2（输入端口名当变量，给输出端口名赋值）": "y = x * 2 (use the input port name as a variable and assign a value to the output port name)",
	"{0} {1}": "{0} {1}",
	"{0} {1} {2}": "{0} {1} {2}",
	"{0} {1} 失败{2}": "{0} {1} failed {2}",
	"{0} {1} 详情": "{0} {1} details",
	"{0} {1}{2}": "{0} {1}{2}",
	"{0} · 文件保留": "{0} · File retention",
	"{0} · 项目设置": "{0} · Project settings",
	"{0} › {1}编辑 {2}": "{0} › {1}Edit {2}",
	"{0} › 编辑 {1}": "{0} › Edit {1}",
	"{0} 个工具": "{0} tools",
	"{0} 个文件": "{0} files",
	"{0} 个文件 · {1}": "{0} files · {1}",
	"{0} 个进程 · {1} 个运行中": "{0} processes · {1} running",
	"{0} 会话操作": "{0} session operation",
	"{0} 分段": "{0} segment",
	"{0} 分钟前": "{0} minutes ago",
	"{0} 天前": "{0} days ago",
	"{0} 学习进度 {1}%": "{0} learning progress {1}%",
	"{0} 小时前": "{0} hours ago",
	"{0} 开关": "Toggle {0}",
	"{0} 成果操作": "{0} result operation",
	"{0} 文本预览": "{0} text preview",
	"{0} 文档": "{0} Documentation",
	"{0} 次调用": "{0} calls",
	"{0} 段": "{0} segment",
	"{0} 的操作": "Operation for {0}",
	"{0} 的格式工具": "Formatting tools for {0}",
	"{0} 的过程": "Process for {0}",
	"{0} 秒": "{0} seconds",
	"{0} 至 {1}": "{0} to {1}",
	"{0} 行": "{0} rows",
	"{0} 详情": "{0} details",
	"{0} 附件操作": "{0} attachment operation",
	"{0} 项 · 文件保留": "{0} items · File retained",
	"{0} 项目操作": "{0} project operations",
	"{0}/.lam/config/subagent/settings.json": "{0}/.lam/config/subagent/settings.json",
	"{0}/{1} 在线": "{0}/{1} online",
	"{0}s 后重试：{1}": "Retry after {0}s: {1}",
	"{0}{1}": "{0}{1}",
	"{0}关闭 {1}": "{0} off {1}",
	"{0}内容": "{0} content",
	"{0}分": "{0} points",
	"{0}原上下文已保留": "{0}The original context has been retained",
	"{0}向 {1} 发送消息": "{0} sent a message to {1}",
	"{0}天": "{0} days",
	"{0}小时": "{0} hours",
	"{0}必须是正数": "{0} must be a positive number",
	"{0}接收 {1} 的消息": "{0} receives message from {1}",
	"{0}操作": "{0} operation",
	"{0}月{1}日": "{0} month {1} day",
	"{0}标题": "{0} title",
	"{0}说明": "{0} Description",
	"{0}运行详情": "{0} operation details",
	"{0}颜色节点": "{0} color node",
	"{0}（{1}–{2}）": "{0} ({1}–{2})",
	"{0}（当前配置）": "{0} (current configuration)",
	"{0}，不可点击": "{0}, not clickable",
	"{0}，打开子代理面板": "{0}, open subagent panel",
	"· 优先级": "· Priority",
	"· 历史": "· History",
	"· 对话": "· Dialogue",
	"· 将自动添加模板内模型": "· In-template models will be added automatically",
	"· 已登录": "· Logged in",
	"· 来源：": "· Source:",
	"· 运行": "· Run",
	通过: "Passed",
	"。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 上下文」内编辑。": ". Injection order: first global constraints (.lam/core/config/AGENTS.md), then this file, and add the two. Global constraints are edited in \"Settings → Context\".",
	"「{0}」文件夹里的方案 — 点开读全文，就绪后开工。": "The plan in the \"{0}\" folder - click to read the full text and start working when ready.",
	"」将被删除": "\"will be deleted\"",
	"」将被删除，且无法恢复。": "\" will be deleted and cannot be restored.",
	"」文件夹里的方案 — 点开读全文，就绪后开工。": "\"The plan in the folder - click to read the full text and start working when ready.",
	"」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。": "\"Folder; it will appear here after writing. The plan is an ordinary Markdown document, you can also create a new one to write.",
	"」还有没保存的内容，离开就会丢掉。": "\"There are unsaved contents and they will be lost when you leave.\"",
	"一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。": "A Step is a model response and its subsequent tool results; 0 Steps are retained by default, and the history will be summarized; then the program will append the original text of the latest 20 user instructions as numbered \"Recent user messages\" paragraphs. Older entries are silently discarded when the token budget is insufficient.",
	"一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务， 你的数据与配置都留在本机。": "A local-first Agent Workbench: Manage sessions, memories, and automated tasks, while your data and configuration stay local.",
	一句话说明这个技能的用途: "Explain the purpose of this skill in one sentence",
	一次性: "Disposable",
	"一次性触发器需要 at 时间": "One-time trigger requires at time",
	上一步: "Previous step",
	上一页附件: "Attachment on previous page",
	上下文: "Context",
	"上下文 {0}（{1}）": "Context {0} ({1})",
	"上下文、输出、Temperature 与高级适配": "Context, Output, Temperature and Advanced Adaptation",
	上下文占用: "Context occupied",
	上下文压缩: "Context compression",
	上下文已压缩: "Context compressed",
	上下文窗口: "Context window",
	上下文菜单: "Context menu",
	"上传中…": "Uploading...",
	上传失败: "Upload failed",
	"上传失败 {0} 个 — {1}": "Upload failed {0} — {1}",
	上传文件: "Upload file",
	"上传文件，或让助手把要留存的产出归入资料库。": "Upload files, or ask the assistant to save outputs to the library.",
	上移: "Move up",
	"上移 {0}": "Move up {0}",
	上级目录: "Parent directory",
	上页: "Previous page",
	下一个模式: "Next mode",
	下一页附件: "Next page attachment",
	下次: "Next time",
	下移: "Move down",
	"下移 {0}": "Move down {0}",
	"下载 {0}%": "Download {0}%",
	下载中: "Downloading",
	"下载中…": "Downloading...",
	下载安装包: "Download the installation package",
	"下载完成 100%": "Download completed 100%",
	"下载完成后点击「立即安装」。": "After downloading, click \"Install Now\".",
	"下载完成后请先退出 Sunday，再运行安装包完成升级。": "After downloading, please exit Sunday before running the installation package to complete the upgrade.",
	下页: "Next page",
	不使用代理的地址: "Address without proxy",
	不可用: "Not available",
	不归档: "Not archived",
	不迭代: "Not iterating",
	不限: "No limit",
	"与运行时的确认通道已断开，恢复连接后才能提交选择。": "The confirmation channel to the runtime has been disconnected and the selection cannot be submitted until the connection is restored.",
	个: "indivual",
	"个 · 工作流 revision": "Individual · Workflow revision",
	个产物: "products",
	个人: "Personal",
	个文件: "files",
	个条目: "items",
	个模型: "models",
	"个模型，可来自多个供应商": "models, can be from multiple vendors",
	个节点: "nodes",
	中: "Medium",
	"中止（默认）": "Abort (default)",
	中继: "Relay",
	"中继.{0}": "Relay.{0}",
	中继点: "Relay point",
	中间产物: "Intermediate product",
	"中（默认）": "Medium (default)",
	"为 {0} 添加第一个模型": "Adding first model for {0}",
	"为不同工作模式配置模型可用的工具。": "Tools available for configuring models for different working modes.",
	"为供应商添加一个可调用的模型。": "Add a callable model for suppliers.",
	主导航: "Main navigation",
	主界面: "Main interface",
	主题: "Theme",
	"主题会即时同步到当前 Sunday 界面。": "The theme will be instantly synchronized to the current Sunday interface.",
	"主题和密度只影响当前 Sunday 界面。": "Theme and density only affect the current Sunday interface.",
	主题预设: "Theme Presets",
	"之后可在 Sunday 设置中继续添加供应商、模型或调整权限模式。": "You can continue to add suppliers, models or adjust permission modes in the Sunday settings later.",
	事件: "Event",
	"事件 · {0}": "Event · {0}",
	"事件审计（": "Event Audit (",
	事件类型: "Event type",
	"事件类型，如 artifact.changed": "Event type, such as artifact.changed",
	"事件触发器需要 event_type": "Event trigger requires event_type",
	于: "in",
	产品发布: "Product Release",
	产物: "Product",
	人工任务: "Human task",
	人工任务已提交: "Human task has been submitted",
	人工协作: "Human collaboration",
	人工审批: "Human approval",
	"仅在需要时暴露给 Agent": "Exposed to Agent only when needed",
	"仅展示用户、中间产物与产物三类。移除只改变成果库状态，不删除文件。": "Only three categories of users, intermediate products and products are displayed. Removing only changes the status of the results library and does not delete the files.",
	"仅支持 .zip 安装包：{0}": "Only .zip installation package is supported: {0}",
	仅用于建立设备信任: "Only used to establish device trust",
	从一个新会话开始: "Starting from a new session",
	"从左侧文件树打开一篇笔记。": "Open a note from the file tree on the left.",
	"从左侧添加一个模型供应商，开始使用 Sunday。": "Add a model provider from the left to start using Sunday.",
	从当前环境导入: "Import from current environment",
	从成果库移除: "Remove from results library",
	"从成果库移除 (": "Removed from repository (",
	"从成果库移除 {0}": "Remove {0} from the artifact library",
	"从成果库移除？": "Remove from results library?",
	从收藏移除: "Remove from favorites",
	从此处另开会话: "Open a new session from here",
	从此节点运行: "Run from this node",
	"从此节点运行…": "Running from this node...",
	"从第 {0} 行": "From line {0}",
	从设备文件中选择: "Select from device file",
	从资料库移除: "Remove from library",
	代码: "Code",
	代码开发: "Code Development",
	任务: "Task",
	"任务 {0}…": "Task {0}...",
	"任务创建后，这里会显示每次运行的时间与结果。": "After the task is created, the time and results of each run will be displayed here.",
	任务已处理: "Task processed",
	任务数量: "Number of tasks",
	任务标题: "Task title",
	任务类型: "Task type",
	"任务类型 {0}": "Task type {0}",
	"任务类型“{0}”重复，请保留一条。": "Task type \"{0}\" is duplicated, please keep one.",
	"任务运行中，请先停止任务再分叉": "The task is running, please stop the task before forking.",
	"任务运行中，请先停止任务再回退": "The task is running, please stop the task first and then roll back.",
	"任务运行中，请先停止任务再编辑": "The task is running, please stop the task before editing.",
	任务页签: "Task tab",
	份方案: "plan",
	优先级: "Priority",
	"优先级 {0}": "Priority {0}",
	会参与激活: "Will participate in activation",
	会话: "Session",
	会话与项目: "Sessions and Projects",
	会话已重命名: "Session renamed",
	会话操作: "Session operations",
	会话标题: "Session title",
	估算: "Estimated",
	位置: "Location",
	低: "Low",
	余烬渐变: "Ember Gradient",
	作为引导发送: "Sent as boot",
	"使用官方模板自动填充连接信息和模型。": "Use official templates to automatically populate connection information and models.",
	"使用选定模型生成结果。": "Generate results using the selected model.",
	"使用默认应用打开？": "Open with default app?",
	"例如 C:\\certs\\root-ca.pem": "For example C:\\certs\\root-ca.pem",
	"例如 deepseek-v4-flash": "e.g. deepseek-v4-flash",
	"例如 http://127.0.0.1:7890": "For example http://127.0.0.1:7890",
	"例如 localhost,127.0.0.1,::1,.example.com,*.corp.com": "For example, localhost,127.0.0.1,::1,.example.com,*.corp.com",
	"例如：Free": "For example: Free",
	"例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议": "For example: Review the submissions in the last 24 hours, summarizing possible bugs and repair suggestions",
	"例如：invoice.created": "For example: invoice.created",
	"例如：quality >= 0.8": "For example: quality >= 0.8",
	"例如：代码审查": "Example: Code Review",
	"例如：偏好": "Example: Preferences",
	"例如：导出显示进度": "For example: Export shows progress",
	"例如：我的供应商": "Example: My supplier",
	"例如：手机项目": "For example: mobile phone project",
	"例如：每日同步": "Example: Daily synchronization",
	"例如：用户偏好.md": "Example: UserPreferences.md",
	"例如：迭代计划": "Example: Iteration Plan",
	供应商: "Provider",
	供应商列表: "Supplier list",
	供应商名称: "Supplier name",
	供应商已删除: "Supplier deleted",
	供应商已更新: "Supplier updated",
	供应商已添加: "Supplier added",
	供应商空状态: "Supplier empty status",
	供应商详情: "Supplier details",
	供应商配置: "Supplier configuration",
	依赖: "Dependencies",
	依赖就绪: "Dependencies ready",
	依赖未知: "Unknown dependency",
	依赖缺失: "Missing dependency",
	侧栏滚动条: "Sidebar scroll bar",
	拖动调整左侧栏宽度: "Drag to resize the left column",
	便签: "Notes",
	"便签.{0}": "Note.{0}",
	保存: "Save",
	保存中: "Saving",
	"保存中…": "Saving...",
	"保存为所有项目的全局基线；项目可单独覆盖。": "Saved as global baseline for all projects; projects can be overridden individually.",
	保存供应商: "Save supplier",
	"保存冲突，请选择处理方式": "Saving conflict, please choose a processing method",
	"保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。": "Save conflict: The remote version has been updated. Please choose to use the remote one, or keep it local and try again.",
	保存到: "Save to",
	"保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global": "Save to global configuration ~/.lam/core/config/subagent/guide.md. Project-level configuration should be edited within the project settings. Leave it blank and save to restore to the built-in default. CLI: core subagent guide show/set/edit --scope global",
	"保存到项目配置 {0}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>": "Saving to project configuration {0}/.lam/config/subagent/guide.md. Save as blank to remove the project-level configuration and fall back to the inherited global/built-in defaults. CLI: core subagent guide show/set/edit --scope project --work-root <root>",
	"保存到项目配置 {0}/.lam/config/subagent/settings.json。": "Save to project configuration {0}/.lam/config/subagent/settings.json.",
	"保存后将移除当前项目覆盖，恢复继承全局策略。": "After saving, the current project override will be removed and the global policy inheritance will be restored.",
	"保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。": "Newly initiated model, MCP and command calls after saving will immediately follow the new settings; connected MCP services and running background commands need to be restarted.",
	"保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "Saved in the app's private SQLite configuration for this device. Please edit project-level rules in \"Project Settings → Project\", and the two will be added together to inject system prompt words.",
	"保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。": "Saved in this device's app-private SQLite configuration, global rules are overlayed to the local workspace.",
	"保存失败，修改仍保留在当前编辑器。": "Saving failed, modifications remain in the current editor.",
	"保存失败：{0}": "Save failed: {0}",
	"保存失败：{0}。你的草稿仍保留，请核对重合区域。": "Save failed: {0}. Your draft is still there, please check the overlapping areas.",
	"保存失败：笔记已被更新，你的草稿仍保留。": "Save failed: The note has been updated and your draft remains.",
	保存工作流: "Save workflow",
	"保存工作流（有未保存修改）": "Save workflow (with unsaved modifications)",
	保存并切换: "Save and switch",
	保存并继续: "Save and continue",
	保存成员: "Save members",
	保存模型: "Save model",
	保存触发器: "Save trigger",
	保存配置: "Save configuration",
	保持电脑运行: "Keep your computer running",
	"保留最近的 Step": "Keep the most recent Step",
	保留本地修改并用远端版本号重试保存: "Keep local modifications and try saving again with remote version number",
	保留本地并重试: "Keep local and try again",
	信任: "Trust",
	修改于: "Modified on",
	"修改后需重启后端生效。": "The backend needs to be restarted after modification to take effect.",
	"修改范围：原 {0} 行起，新 {1} 行起": "Modification range: starting from the original {0} line, starting from the new {1} line",
	候选结论: "Candidate conclusion",
	值: "value",
	"停止失败：{0}": "Stop failed: {0}",
	停止工作流: "Stop workflow",
	停止运行: "Stopped running",
	"停止运行（子代理仍在运行）": "Stopped (subagent is still running)",
	停用: "Disable",
	"停用失败：{0}": "Deactivation failed: {0}",
	允许工作目录外: "Allow outside working directory",
	允许手机控制这台电脑: "Allow phone to control this computer",
	允许访问工作目录以外: "Allow access outside working directory",
	"允许读写工作目录之外的路径。": "Allow reading and writing of paths outside the working directory.",
	先保存工作流再排队: "Save workflow before queuing",
	先保存工作流再运行: "Save the workflow before running it",
	先在左侧选择一个项目: "Select an item on the left first",
	"先在左侧选择一个项目 — 资料库跟随项目。": "Select a project on the left first - the library follows the project.",
	"先在左侧选择一个项目 — 资料库跟随项目文件夹。": "Start by selecting a project on the left - the library follows the project folder.",
	"先提供背景方向，其他区域可继续单独调整。": "Provide the background direction first, and other areas can continue to be adjusted individually.",
	"先用 read_file 读回这份方案（它在当前项目之外，读到它需要你先申请访问批准），对照仓库现状核对需求与步骤，有出入的地方先记下结论；": "First use read_file to read back the plan (it is outside the current project, and reading it requires you to apply for access approval first), check the requirements and steps against the current situation of the warehouse, and write down the conclusions if there are any discrepancies;",
	"先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；": "First use read_file to read back the plan, check the requirements and steps against the current situation of the warehouse, and if there are any discrepancies, write down the conclusion and update the plan file;",
	先进入一个项目: "Enter a project first",
	"先进入一个项目，再操作它的记忆": "Enter a project first, then operate its memory",
	先选一个工作目录: "Select a working directory first",
	"克制的中性灰阶。": "Restrained neutral grayscale.",
	"全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。": "Global context. Injection order: global AGENTS.md (priority 5) → project AGENTS.md (10); addition/except of load_context is globally superimposed to each workspace.",
	全局上下文加载: "Global context loading",
	"全局基线适用于所有项目；项目可按同名任务类型覆盖。": "Global baselines apply to all projects; projects can be overridden by task type with the same name.",
	"全局搜索：跨项目查找会话、消息与学习资料。": "Global search: Find conversations, messages, and learning resources across projects.",
	全局约束: "Global constraints",
	"全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 {0} 条。": "Global rules are used as the baseline; only project coverage is edited here, and the task type with the same name is subject to project rules. There are currently {0} items merged.",
	全局记忆: "Global memory",
	"全应用的出口流量走哪里，以及它们信任哪个根证书。": "Where does all application egress traffic go, and which root certificates do they trust.",
	全选: "Select all",
	全部: "All",
	全部删除: "Delete all",
	全部工具: "All tools",
	全部工具可用: "All tools available",
	全部状态: "All status",
	全部类型: "All types",
	全部角色: "All characters",
	公式: "Formula",
	"六位数字码 5 分钟内有效且只能使用一次": "The six-digit code is valid within 5 minutes and can only be used once",
	"共 {0} 个 · 已信任 {1}{2}": "{0} total · {1} trusted{2}",
	"共 {0} 个 · 已启用 {1}": "{0} in total · {1} enabled",
	关于与更新: "About and updates",
	关系: "Relationship",
	关系图: "Relationship diagram",
	关系图例: "Relationship legend",
	关系图加载中: "Relationship diagram loading",
	关联: "Association",
	关闭: "Close",
	关闭并保留草稿: "Close and keep draft",
	"恢复默认？": "Reset to defaults?",
	"将清除已发布的主题与当前草稿，无法撤销。": "This clears the published theme and the current draft. It cannot be undone.",
	"主题文件过大，请检查是否误选了其他文件": "Theme file is too large; check that you picked the right file",
	"关闭 Sub Agent": "Close Sub Agent",
	"关闭 {0} 失败": "Failed to close {0}",
	"关闭了 {0}": "{0} is closed",
	"关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。": "The tool is removed from the tool set after closing; when enabled but the API address is empty, the call returns \"Unconfigured graphing API\".",
	关闭工作流标签: "Close workflow label",
	"关闭提示：{0}": "Close prompt: {0}",
	关闭文本预览: "Turn off text preview",
	关闭网格吸附: "Turn off grid snapping",
	关闭节点目录: "Close node directory",
	"关闭设置？": "Close settings?",
	关闭详情: "Close details",
	关闭详细调整: "Turn off detailed adjustments",
	关闭配对码: "Turn off pairing code",
	关闭面板: "Close panel",
	关闭预览: "Close preview",
	其他: "Other",
	其他处理方式: "Other processing methods",
	"其余时间用另一个模式；跨天时段同样有效。": "Use another mode for the rest of the time; cross-day periods are also valid.",
	兼容: "Compatible",
	"兼容旧版 AI 节点。": "Compatible with older versions of AI nodes.",
	"兼容旧版 Python 脚本节点。": "Compatible with older versions of Python script nodes.",
	"兼容旧版分支节点。": "Compatible with older version branch nodes.",
	"兼容旧版转换节点。": "Compatible with legacy conversion nodes.",
	内存中断自动续跑: "Automatically resume running after memory interruption",
	内容宽度: "Content width",
	"内容（content）": "content",
	内核配置: "Kernel configuration",
	内置: "Built-in",
	内置默认: "Built-in default",
	"内置：": "Built-in:",
	写: "Write",
	"写下想法…": "Write down ideas...",
	"写下注释…": "Write a note...",
	"写点什么，助手下次就会读到它。": "Write something and the assistant will read it next time.",
	"决定工具执行前是否需要你确认。": "Determine whether the tool requires your confirmation before execution.",
	"决定模型是否接收图片，以及是否启用推理参数。": "Determines whether the model receives images and whether inference parameters are enabled.",
	"准备开干！": "Ready to start!",
	几号: "What’s the number?",
	出错: "Error",
	分层: "Layering",
	"分支 {0}": "Branch {0}",
	"分支（兼容）": "Branch (compatible)",
	分段: "Segmentation",
	分组: "Grouping",
	"分组.{0}": "Grouping.{0}",
	分组键: "Grouping key",
	切换侧栏: "Toggle sidebar",
	"切换到 ": "Switch to",
	"切换前要如何处理当前草稿？": "How to process the current draft before switching?",
	切换右侧栏: "Toggle right column",
	切换模式: "Switch mode",
	"切换模式，当前 {0}": "Switch mode, currently {0}",
	"列出 {0}": "List {0}",
	列出目录: "List directory",
	列表视图: "List view",
	刚刚: "Just now",
	刚刚打开: "Just opened",
	创建: "Create",
	"创建 {0}": "Create {0}",
	"创建一个模型组来整理所有供应商下的模型。": "Create a model group to organize models under all suppliers.",
	创建中: "Creating",
	"创建中…": "Creating...",
	创建了: "Created",
	创建你的第一个文件夹: "Create your first folder",
	创建分组来整理常用模型: "Create groups to organize commonly used models",
	"创建失败：{0}": "Creation failed: {0}",
	创建定时任务: "Create a scheduled task",
	创建技能: "Create skills",
	创建文件: "Create file",
	创建文件夹: "Create folder",
	"创建文件夹，整理资料库中的方案。": "Create folders to organize plans in the library.",
	创建项目: "Create project",
	删: "Delete",
	删除: "Delete",
	"删除 ": "Delete",
	"删除 Hook？": "Delete Hook?",
	"删除 {0}": "Delete {0}",
	"删除 {0} 行": "Delete row {0}",
	"删除会话及历史？": "Delete session and history?",
	"删除供应商及其模型配置？": "Delete supplier and its model configuration?",
	删除全部队列项和历史: "Delete all queue items and history",
	删除内容: "Delete content",
	"删除子代理 ": "Delete subagent",
	删除容器及其内容: "Delete container and its contents",
	删除已结束历史: "Delete ended history",
	删除待发送内容: "Delete content to be sent",
	"删除技能 {0}": "Delete skill {0}",
	"删除技能及目录？": "Delete skills and directories?",
	删除文件夹: "Delete folder",
	"删除文件夹（含里面全部条目）": "Delete folder (including all entries in it)",
	删除方案: "Delete plan",
	删除标记: "Delete mark",
	"删除模型组（模型保留）？": "Delete model group (model retained)?",
	"删除模型配置？": "Delete model configuration?",
	删除此消息及之后内容: "Delete this message and subsequent content",
	删除此轮及之后内容: "Delete this round and subsequent content",
	删除组: "Delete group",
	"删除角色分配 {0}": "Delete role assignment {0}",
	删除记忆: "Delete memory",
	删除连线: "Delete connection",
	"删除选中元素（{0}）": "Delete selected element ({0})",
	删除项目: "Delete project",
	"删除项目及会话记录？": "Delete project and session records?",
	刷新: "Refresh",
	"刷新中…": "Refreshing...",
	刷新人工任务: "Refresh human tasks",
	刷新成果库: "Refresh the results library",
	刷新激活状态: "Refresh activation status",
	刷新笔记文件树: "Refresh note file tree",
	刷新进程列表: "Refresh process list",
	刷新队列: "Refresh queue",
	前置: "Prefix",
	剪切: "Cut",
	加入队列: "Join queue",
	加粗: "Bold",
	"加载 {0} 失败：{1}": "Failed to load {0}: {1}",
	加载中: "Loading",
	"加载中...": "Loading...",
	"加载中…": "Loading...",
	"加载失败：": "Loading failed:",
	"加载失败：{0}": "Loading failed: {0}",
	加载技能: "Loading skills",
	"加载技能 · {0}": "Loading skills · {0}",
	加载类型: "Loading type",
	助手回复: "Assistant reply",
	勾选后从成果库移除: "Remove from the results library after checking",
	匹配器: "Matcher",
	"匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。": "Requests matching these hosts will be connected directly without going through the HTTP proxy; the command tool writes NO_PROXY according to the same rules. Multiple rules are separated by commas.",
	单次: "Single",
	"单次 (single)": "single",
	"单次 · {0}": "Single · {0}",
	单步调试: "Single-step debugging",
	"单步运行中…": "Single stepping...",
	卸载: "Uninstall",
	"卸载插件及目录？": "Uninstall plug-ins and directories?",
	历史: "History",
	"压缩保留最近 Step 数": "Compression retains the most recent Step number",
	压缩后: "After compaction",
	压缩未完成: "Compression not completed",
	原上下文已保留: "The original context has been retained",
	"原上下文已保留 · {0}": "The original context has been retained · {0}",
	原始配置: "Original configuration",
	"原文已变化或暂未加载，无法准确定位。": "The original text has changed or has not been loaded yet, and cannot be accurately located.",
	"原模型「{0}」已不可用，已改用「{1}」": "The original model \"{0}\" is no longer available and has been replaced by \"{1}\"",
	去登录: "Go to login",
	参数: "Parameters",
	双击打开: "Double-click to open",
	双击文本预览: "Double-click text preview",
	"发现新版本 v": "New version v found",
	"发现新版本 v{0}": "New version v{0} found",
	"发现新版本 v{0}，点击下载": "Found new version v{0}, click to download",
	"发现新版本 v{0}，点击打开下载页": "Found new version v{0}, click to open the download page",
	发现新版本时会在顶部显示提示条: "Display a tooltip at the top when a new version is found",
	发送: "Send",
	取消: "Cancel",
	取消下载: "Cancel download",
	取消任务: "Cancel task",
	取消固定右侧栏: "Unpin right sidebar",
	取消固定左侧栏: "Unpin the left column",
	"取消失败：{0}": "Cancellation failed: {0}",
	取消收藏: "Cancel favorites",
	"取消收藏：{0}": "Cancel collection: {0}",
	"取消暴露为 Agent 工具": "Unexpose as Agent tool",
	取消更新: "Cancel update",
	取消置顶: "Unpin",
	"取消运行 {0}": "Cancel running {0}",
	"取消选择 {0}": "Deselect {0}",
	"只属于「{0}」的记忆 — 模型在会话里读它，你在这里整理它。": "Memory belonging only to \"{0}\" — the model reads it in session, you organize it here.",
	"只改变背景板，聊天区、输入栏和控件保持中性。": "Only the background panel is changed, the chat area, input fields and controls remain neutral.",
	可用模式: "Available modes",
	可用至: "Available to",
	"可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。": "Optional. After filling in the PEM root certificate path, the model requests it as the root of trust, and injects variables such as SSL_CERT_FILE and NODE_EXTRA_CA_CERTS into the MCP and command tools; if left blank, the system trust chain is used.",
	"可选：自然语言格式说明": "Optional: Natural language format description",
	右侧工具: "Tools on the right",
	右侧工具栏: "Right toolbar",
	合并: "Merge",
	"合并多个输入，取首个有效值。": "Combine multiple inputs and take the first valid value.",
	"同一主题在两种模式下保持不同的明暗气质。": "The same theme maintains different light and dark qualities in the two modes.",
	同步项目: "Sync Project",
	名称: "Name",
	名称不能包含路径分隔符: "Name cannot contain path separators",
	"后端进程已停止响应（可能已崩溃）。请重启应用以恢复。": "The backend process has stopped responding (possibly crashed). Please restart the app to recover.",
	"向 Sub Agent 发送消息...": "Send message to Sub Agent...",
	"向 {0} 发送了消息": "Sent message to {0}",
	"向 {0} 发送消息失败": "Failed to send message to {0}",
	向下调整高度: "Adjust height downwards",
	"向供应商 API 发送的模型标识。": "Model ID sent to vendor API.",
	向右调整宽度: "Adjust width right",
	启动时自动检查更新: "Automatically check for updates on startup",
	启用: "Enable",
	"启用 generate_image 工具": "Enable generate_image tool",
	启用了: "Enabled",
	"启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。": "The generate_image tool will upload the tool set only after it is enabled; when it is not enabled, the call will be intercepted.",
	启用或关闭生图工具: "Enable or disable the drawing tool",
	"启用技能 {0}": "Enable skill {0}",
	启用推理预算: "Enable inference budget",
	"启用插件 {0}": "Enable plugin {0}",
	命中: "hit",
	命令: "Command",
	"命令 ": "Command",
	"命令 {0}": "Command {0}",
	"命令…（curl/git/ffmpeg 等）": "Command... (curl/git/ffmpeg, etc.)",
	命令行: "Command line",
	命令输出: "Command output",
	回到子代理最新: "Return to subagent latest",
	回到最新: "Back to latest",
	回到最新消息: "Back to latest news",
	回到编辑: "Return to editing",
	回滚: "Rollback",
	"固定 revision": "fixed revision",
	固定右侧栏: "Fixed right sidebar",
	固定左侧栏: "Fixed left column",
	图标: "Icon",
	图标色彩: "Icon color",
	图片: "Picture",
	"图片加载失败：{0}": "Image loading failed: {0}",
	"图片暂时取不到，重试": "The picture cannot be retrieved temporarily, try again",
	图谱: "Map",
	"在 LamTools 手机端输入此数字": "Enter this number in LamTools mobile app",
	"在会话里让助手写下记忆，它就会出现在这里。": "Ask the assistant to write a memory in a session and it will appear here.",
	"在当前能力范围内自动批准（工作目录外仍会确认）": "Automatically approve within current capabilities (will still be acknowledged outside the working directory)",
	在线: "Online",
	"在聊天里说出你的想法，助手会一边问一边把方案写进「": "Speak your thoughts in the chat, and the assistant will write the plan into \"",
	在里面新建文件夹: "Create a new folder in it",
	在里面新建记忆: "Create new memory in it",
	处理中: "Processing",
	"处理中…": "Processing...",
	处理器类型: "Processor type",
	处理您的日常任务: "Tackle your daily tasks",
	处理方式: "Processing method",
	备注: "Remarks",
	复位: "Reset",
	复制: "Copy",
	复制代码: "Copy code",
	复制回复: "Copy reply",
	复制失败: "Copy failed",
	"复制失败：当前环境无法访问剪贴板": "Copy failed: Clipboard is not accessible in the current environment",
	"复制完整 ID": "Copy full ID",
	"复制完整会话 ID": "Copy full session ID",
	复制数字码: "Copy numeric code",
	复制消息: "Copy message",
	复制路径: "Copy path",
	外观: "Appearance",
	外观模式: "Appearance mode",
	"外部搜索内核（subprocess / http）": "External search kernel (subprocess/http)",
	多模态: "Multimodality",
	"多模态（支持图片）": "Multimodality (supports images)",
	大纲: "Outline",
	失败: "Failed",
	"如 AGENTS.md / CONTEXT.md": "Such as AGENTS.md / CONTEXT.md",
	"如 gpt-image-1 / flux 等，留空使用服务端默认": "Such as gpt-image-1 / flux, etc., leave it blank to use the server default",
	"如 my-skill（字母/数字/._-）": "such as my-skill (letters/numbers/._-)",
	"如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展": "If you need to access independent search tools (such as baidu-serp-api, SearXNG, openserp, etc.), expand in the original configuration",
	"如：我的 DeepSeek": "Such as: My DeepSeek",
	委派子代理: "Delegate subagent",
	"委派子代理：{0}": "Delegating subagent: {0}",
	子代理: "Subagent",
	"子代理 (agent)": "subagent (agent)",
	"子代理 {0}": "Subagent {0}",
	子代理委派策略: "Subagent delegation policy",
	子代理资源统计: "Subagent resource statistics",
	子代理运行中: "Subagent is running",
	"子代理运行中：{0}": "Subagent running: {0}",
	子层: "Sublayer",
	子工作流: "Subworkflow",
	子文档: "Subdocument",
	"字段，例如：": "Field, for example:",
	字节读取完成: "Byte reading completed",
	学习: "Learning",
	"学习、探索、温习": "Learn, explore, review",
	学科: "Subject",
	"安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。": "Security gateway is up; LAN is encrypted using Noise, public network connection is through self-hosted Relay.",
	安全边界: "Security Boundary",
	安装: "Installation",
	"安装中…": "Installing...",
	安装依赖: "Install dependencies",
	安装包约: "Installation package about",
	"安装完成后 Sunday 会自动重新打开。": "Sunday will automatically reopen after installation is complete.",
	安装成功: "Installation successful",
	"安装成功：{0}": "Installation successful: {0}",
	安装插件: "Install plugin",
	"完全编辑、自动批准，并允许访问工作目录外": "Full edit, auto-approve, and allow access outside working directory",
	完全访问: "Full access",
	完全访问已包含: "Full access included",
	"完全访问模式会临时允许访问工作目录之外的路径。": "Full access mode temporarily allows access to paths outside the working directory.",
	完成: "Complete",
	完整归档: "Complete archive",
	"完整归档导出失败：{0}": "Full archive export failed: {0}",
	"完整归档已保存：{0}": "Complete archive saved: {0}",
	"完整归档正在准备中，请稍候。": "The complete archive is being prepared, please wait.",
	"官方发现与 Relay 必须登录": "Official discovery and Relay must be logged in",
	官方模板: "Official template",
	定时任务: "Scheduled tasks",
	"定时任务 › {0}": "Scheduled tasks › {0}",
	"定时任务 › 新建任务": "Scheduled tasks › Create new task",
	"定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。 点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。": "A scheduled task is a long-term instruction given to the Agent: when the time comes, it will start work by itself, and when it is finished, the results will be left in the session. Click \"Create a scheduled task\" in the upper right corner, or directly say \"Do XX at nine o'clock every day\" in the chat.",
	定时任务模板: "Scheduled task template",
	定时切换: "Scheduled switching",
	实时: "real time",
	实时预览: "Live preview",
	实测: "Measured",
	审批: "Approval",
	容器内没有可选元素: "There are no optional elements in the container",
	宽松: "Loose",
	密码: "Password",
	对话: "Dialogue",
	导入: "Import",
	"导入 JSON": "Import JSON",
	"导入失败：{0}": "Import failed: {0}",
	导入工作流: "Import workflow",
	导出: "Export",
	"导出失败（{0}）": "Export failed ({0})",
	"导出失败：{0}": "Export failed: {0}",
	将移除此处的: "Will be removed here",
	"将丢弃：{items}。已完成的工具结果会保留，终止后不能继续。": "Will be discarded: {items}. Completed tool results are kept, and a terminated turn cannot be continued.",
	"尚未启动 Sub Agent": "Sub Agent has not been started yet",
	"尚未生成配对码。": "No pairing code has been generated yet.",
	尚未登录服务器账号: "Not logged in to the server account yet",
	尚未评估: "Not evaluated yet",
	尚未连接: "Not connected yet",
	"尚未配对手机。": "The phone has not been paired yet.",
	尝试: "Try",
	就绪: "Ready",
	局域网: "LAN",
	"局部图超过建议范围（{0} 节点 / {1} 条关系），已保持分页；当前布局在主线程分层计算。": "The partial graph exceeds the recommended range ({0} nodes / {1} relations) and paging has been maintained; the current layout is calculated hierarchically on the main thread.",
	展开: "Expand",
	搜索图层: "Search layers",
	没有匹配的图层: "No matching layers",
	吸附: "Snap",
	辅助线: "Guides",
	父级: "Parent",
	尺寸: "Size",
	宽度: "Width",
	高度: "Height",
	填充: "Fill",
	内容适配: "Fit content",
	固定值: "Fixed",
	未设置: "Unset",
	最小: "Min",
	最大: "Max",
	背景透明度: "Background opacity",
	图片格式无法识别: "Unrecognized image format",
	"SVG 不允许包含脚本": "SVG must not contain scripts",
	"展开 ": "Expand",
	"展开 {0}": "Expand {0}",
	"展开{0}分区": "Expand {0} partition",
	展开全部会话: "Expand all sessions",
	"展开另外 {0} 个会话": "Expand {0} more sessions",
	展开最近会话: "Expand recent conversations",
	展开运行详情: "Expand run details",
	工作业务: "Work business",
	工作区: "Workspace",
	"工作区域保持纯色，颜色只用于控件层级。": "Keep the work area solid, colors are only used at the control level.",
	工作台: "Workbench",
	"工作根目录：": "Working root directory:",
	工作模式列表: "Working mode list",
	工作模式详情: "Working mode details",
	工作流: "Workflow",
	工作流不存在: "Workflow does not exist",
	工作流名称: "Workflow name",
	工作流对话: "Workflow dialog",
	工作流有未保存修改: "Workflow has unsaved modifications",
	工作流检查器: "Workflow Inspector",
	工作流画布: "Workflow canvas",
	工作流画布操作: "Workflow canvas operations",
	工作流缩略图: "Workflow thumbnail",
	工作流节点操作: "Workflow node operations",
	工作流节点目录: "Workflow node directory",
	工作流触发器与激活: "Workflow triggers and activation",
	工作流资源: "Workflow resources",
	工作流运行输入: "Workflow run input",
	工作流连线操作: "Workflow connection operation",
	工作流队列与历史: "Workflow queues and history",
	工作环境: "Work environment",
	"工作环境：{0}": "Working environment: {0}",
	工作目录: "Working directory",
	"工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。": "Read, write and command line access outside the working directory will ask for your confirmation first and then execute it after approval.",
	工作目录外访问: "Access outside working directory",
	"工作目录外访问设置保存失败，已回滚：{0}": "Failed to save access settings outside the working directory and has been rolled back: {0}",
	工作目录外需确认: "Need to confirm outside the working directory",
	工具: "Tools",
	"工具 {0} 不可用：请求了当前环境没有注册的工具。": "Tool {0} is not available: A tool that is not registered in the current environment was requested.",
	工具不可用: "Tool not available",
	"工具不可用：{0}": "Tool not available: {0}",
	工具列表: "Tool list",
	工具执行前请求批准: "Approval requested before tool execution",
	工具模式: "Tool modes",
	工具调用: "Tool call",
	工具集: "Toolset",
	左对齐: "left aligned",
	已中断: "Interrupted",
	"已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。": "A forked session has been created from here; only the conversation history is copied, not the workspace or runtime state.",
	已保存: "Saved",
	"已保存，重启后端后生效。": "Saved, it will take effect after restarting the backend.",
	"已保存：{0}": "Saved: {0}",
	"已保留本地修改，正在重试保存…": "Local modifications have been retained, retrying to save...",
	已信任: "Trusted",
	已修改: "Modified",
	已停用: "Disabled",
	"已停用。": "Disabled.",
	已停用触发器: "Trigger disabled",
	已允许: "Allowed",
	已关闭: "Closed",
	已创建任务: "Task created",
	"已创建：{0}": "Created: {0}",
	"已删除此轮及之后的对话；文件与成果保持不变。": "This round and subsequent conversations have been deleted; files and results remain unchanged.",
	"已加入队列：{0}": "Queued: {0}",
	已压缩: "Compressed",
	"已发布 v": "Published v",
	已取消: "Canceled",
	"已取消完整归档导出。": "Full archive export canceled.",
	已取消暴露: "Exposure canceled",
	已取消队列运行: "Queue run canceled",
	已启用: "Enabled",
	已复制: "Copied",
	"已复制 {0} 个元素": "{0} elements copied",
	"已复制完整会话 ID": "Full session ID copied",
	已失联: "Lost contact",
	已完成: "Completed",
	"已完成|已失败|已中断|已取消": "Completed|Failed|Interrupted|Cancelled",
	"已导入：{0}": "Imported: {0}",
	"已导出工作流 JSON": "Workflow JSON exported",
	"已导出：{0}": "Exported: {0}",
	已就绪: "Ready",
	"已就绪 · 已配置密钥": "Ready · Key configured",
	已开启: "Enabled",
	已截断: "Truncated",
	已打开: "Already open",
	已收藏: "Favorite",
	"已新增触发器，请填写配置后保存。": "A new trigger has been added. Please fill in the configuration and save it.",
	"已是最新版本（v": "Already the latest version (v",
	"内部测试版，已跳过应用内更新检查（请用 update-constant.ps1 更新）": "Internal test build: in-app updates are skipped (use update-constant.ps1 to update).",
	已暂停: "Paused",
	"已暂停（单步）": "Paused (single step)",
	已暴露: "Exposed",
	"已暴露：{0}": "Exposed: {0}",
	"已替换并激活。": "Replaced and activated.",
	已替换并激活触发器: "Trigger replaced and activated",
	已标记: "Flagged",
	"已添加 {0} 个目录": "{0} directories added",
	"已添加节点：{0}": "Node added: {0}",
	"已清理 {0} 个队列/历史项": "{0} queue/history items cleared",
	"已激活。": "Already activated.",
	已激活触发器: "Trigger activated",
	已登录: "Already logged in",
	已禁用: "Disabled",
	已移除: "Removed",
	"已粘贴 {0} 个元素": "{0} elements pasted",
	已获取: "Obtained",
	已设为默认模型: "Already set as default model",
	已评估但未通过: "Evaluated but failed",
	"已读取：{0}": "Read: {0}",
	"已调用{0}个工具…": "{0} tools have been called...",
	已跳过: "Skipped",
	已运行: "Already running",
	已连接: "Connected",
	已退出: "Exited",
	已选: "Selected",
	已选中容器: "Container selected",
	"已通过，掌握{0}": "Passed, mastered {0}",
	已配对移动设备: "Mobile device paired",
	已配对设备: "Device paired",
	"已配置（留空保持原密钥）": "Already configured (leave blank to keep the original key)",
	已采用远端版本: "Remote version has been adopted",
	"已重命名：{0}": "Renamed: {0}",
	已锁定区域: "Region locked",
	布局: "Layout",
	带输入运行: "Run with input",
	常量: "Constant",
	常量值: "Constant value",
	"并发 {0}": "Concurrency {0}",
	并发上限: "Concurrency limit",
	库根: "Kugan",
	应用: "Apply",
	建议: "Suggestion",
	建议模型: "Suggested model",
	"建议模型 {0}": "Suggested model {0}",
	开启: "Enable",
	"开启后生成设备身份和一次性六位数字配对码。": "Generate device identity and one-time six-digit pairing code after turning it on.",
	开启手机控制: "Enable mobile phone control",
	开启网格吸附: "Enable grid snapping",
	开始: "Start",
	开始使用: "Getting started",
	"开始前需要配置一个模型供应商，让 Agent 能思考与回复。": "Before starting, you need to configure a model provider so that the Agent can think and reply.",
	"开始时间（可选）": "Start time (optional)",
	开始配置: "Start configuration",
	开工: "Start work",
	引导: "Boot",
	引擎: "Engine",
	引用: "Reference",
	"引用外部工作流，iterate 控制执行模式": "Reference to external workflow, iterate controls execution mode",
	归到文件夹: "Return to folder",
	归属此账号的设备: "Devices belonging to this account",
	"当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明": "When the main model is a text model and attachments such as pictures/videos need to be understood, the ability prompt word will guide the main Agent to use this model to delegate sub_agent to view it. Show only declared",
	当前主题: "Current topic",
	当前会话: "Current session",
	当前会话可临时切换: "The current session can be temporarily switched",
	当前会话说明: "Current session description",
	"当前使用内置默认：{0}": "Currently using built-in default: {0}",
	当前供应商: "Current supplier",
	"当前全局基线：{0}": "Current global baseline: {0}",
	当前六位数字配对码: "Current six-digit pairing code",
	当前六位配对码: "Current six-digit pairing code",
	"当前内核：{0}": "Current core: {0}",
	当前显示: "Currently displayed",
	"当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。": "Relay is not currently configured, and the mobile phone cannot discover this computer based on the digital code alone; please configure the remote relay service first.",
	"当前来源：全局配置": "Current source: global configuration",
	"当前来源：内置默认（未配置全局 guide）": "Current source: built-in default (global guide not configured)",
	"当前来源：继承全局 / 内置默认（未配置项目级 guide）": "Current source: inherited global/built-in default (no project-level guide configured)",
	"当前来源：项目配置": "Current Source: Project Configuration",
	当前桌面工作环境: "Current desktop working environment",
	当前模型组: "Current model group",
	当前模式: "Current mode",
	当前模式由插件提供: "The current mode is provided by a plugin",
	"当前步骤：第 {0} 步，{1}，{2}": "Current step: step {0}, {1}, {2}",
	"当前没有 checklist": "There is currently no checklist",
	当前没有可分叉的会话: "There are currently no forkable sessions",
	当前没有可回退的会话: "There are currently no sessions to roll back",
	"当前没有可用的项目，无法打开文件": "There are currently no projects available and the file cannot be opened.",
	当前没有可编辑的会话: "There are currently no editable sessions",
	当前没有排队运行: "There are currently no queued runs",
	"当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 {0} 条。": "There is currently no project coverage, and the global baseline will be used; after a new project rule is added to the task type with the same name, it will be covered by the project. {0} items are currently in effect.",
	当前版本: "Current version",
	"当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。": "Current version and software updates (priority is given to reading the official website update list, and falling back to GitHub Releases when the official website is unreachable).",
	"当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）": "The current environment does not support drag-and-drop installation (please use Release URL to paste and install)",
	当前环境不支持文件导出: "File export is not supported in the current environment",
	当前环境不支持文件选择: "File selection is not supported in the current environment",
	当前环境不支持附件选择: "Attachment selection is not supported in the current environment",
	"当前笔记没有保存处理，修改仍保留。": "The current note has not been saved and the modifications are still retained.",
	当前组: "Current group",
	"当前继承全局有效策略：{0}": "Currently inheriting the global effective policy: {0}",
	当前计划: "Current plan",
	当前账号: "Current account",
	"当前选择：{0}": "Current selection: {0}",
	当前配对码: "Current pairing code",
	当前队列: "Current queue",
	当前项目: "Current project",
	"当前项目没有本地覆盖。": "The current project has no local overrides.",
	"当前项目覆盖：{0}": "Current project coverage: {0}",
	"当前项目还没有可用会话。新建会话后即可开始工作。": "There are no sessions available for the current project. Create a new session and start working.",
	当前默认状态: "Current default state",
	待你选择: "Waiting for your choice",
	待处理: "Pending",
	待处理项: "Pending items",
	待定: "Pending",
	待审核: "Pending review",
	待接入: "Waiting for access",
	待评定: "Pending evaluation",
	待配置: "To be configured",
	"待配置 · 缺少 API Key": "To be configured · Missing API Key",
	循环: "Loop",
	"循环 (loop)": "loop",
	必填: "required",
	"必须与所选供应商的 API 基础 URL 一致。": "Must match the selected vendor's API base URL.",
	快捷操作: "Quick operation",
	快速开始: "Quick start",
	思索: "Thinking",
	思考: "Thinking",
	"思考中…": "Thinking...",
	"思考了{0}s": "Thought {0}s",
	思考了一会: "Thinking for a while",
	思考模式: "Thinking model",
	思考等级: "Thinking level",
	思考等级选项: "Think about level options",
	恢复: "Recovery",
	"恢复 {0}": "Restore {0}",
	恢复到成果库: "Restore to results library",
	恢复默认: "Restore default",
	"想了解什么？": "What do you want to know?",
	"想如何整理笔记…": "How to organize notes...",
	"想学什么…": "What do you want to learn...",
	成员: "Member",
	成果: "Results",
	成果列表: "Results list",
	成果库: "Results library",
	成果筛选: "Results filtering",
	"我想学{0}，给我讲一下": "I want to learn {0}, tell me about it",
	"或粘贴 GitHub Release URL：": "Or paste the GitHub Release URL:",
	截止: "Deadline",
	"所选目录在工作区之外，已保留绝对路径": "The selected directory is outside the workspace and the absolute path has been reserved",
	手动: "Manual",
	手动触发无需排程: "Manual triggering without scheduling",
	手动运行: "Run manually",
	"手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。 自动送达（账号直传）尚未接入，先用导出／导入这一步。": "Make the plan on the mobile phone and start the work on the computer: The plan is first stored on the mobile phone, and can be checked and executed after being imported on the desktop. Automatic delivery (account direct transfer) has not been connected yet, please use the export/import step first.",
	手机控制: "Mobile",
	"手机控制命令将在桌面 Tauri 运行时启用": "Mobile control commands will be enabled when desktop Tauri is running",
	"手机控制命令将在桌面 Tauri 运行时启用。": "Phone control commands will be enabled when desktop Tauri is running.",
	手机控制未能启动: "Mobile phone control failed to start",
	"手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。": "After the mobile phone submits the digital code, Relay only parses the connection metadata; the actual pairing authentication and session data are still completed through the Noise encrypted tunnel.",
	"手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。": "The mobile phone has not yet connected to the memory directory: ask the assistant to use the memory tool to organize it in the session, or connect to the desktop to browse here.",
	手机配对: "Mobile phone pairing",
	打开: "Open",
	"打开 ": "Open",
	"打开 {0}": "Open {0}",
	"打开 {0} 的项目记忆": "Open project memory for {0}",
	"打开「{0}」失败：{1}": "Failed to open \"{0}\": {1}",
	"打开会话 {0}": "Open session {0}",
	打开右侧面板: "Open the right panel",
	"打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。": "After opening, it prevents the system from entering idle sleep (manual sleep and closed sleep are not affected), and long tasks will not be interrupted.",
	"打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。": "After opening, if no one answers the model's question card for more than 5 minutes, \"User Skip\" will be returned and the current round will continue. Approval cards that require your authorization will not be affected and will be waiting for you to process.",
	"打开完整设置（账号与设备）": "Open full settings (account and device)",
	打开工作区: "Open workspace",
	打开左侧会话栏: "Open the left conversation bar",
	"打开快捷操作，当前模式 {0}": "Open shortcut operation, current mode {0}",
	打开文件夹: "Open folder",
	"打开文件夹 {0}": "Open folder {0}",
	打开的工作流: "Open workflow",
	"打开笔记 {0}": "Open note {0}",
	打开视窗: "Open window",
	打开账号与设备: "Open accounts and devices",
	打开附件失败: "Failed to open attachment",
	"打开附件选择器失败：{0}": "Failed to open attachment selector: {0}",
	"打开项目 {0}": "Open project {0}",
	执行: "Execute",
	"执行 Python 脚本，并通过端口传递变量。": "Execute a Python script and pass variables through the port.",
	执行中: "Executing",
	执行前显示给用户的状态文字: "Status text displayed to the user before execution",
	"执行动作？": "Perform action?",
	执行步骤: "Execute steps",
	"执行进度：{0}": "Execution progress: {0}",
	扩展: "Extension",
	扩展提示: "Extension prompt",
	"扩展自身的审批等级与 hard block 由各自的管理入口负责。": "The approval level and hard block of the extension itself are handled by the respective management portal.",
	"扫描中…": "Scanning...",
	扫描目录: "Scan directory",
	批准: "Approved",
	技能: "Skills",
	"技能加载后 Agent 应遵循的完整指引……": "The complete guidelines that the Agent should follow after the skill is loaded...",
	把这份方案交给当前会话执行: "Hand over this plan to the current session for execution",
	折叠: "Collapse",
	"折叠 {0}": "Collapse {0}",
	"折叠{0}分区": "Collapse {0} partition",
	折叠最近会话: "Collapse recent conversations",
	拍摄一张新照片: "Take a new photo",
	拒绝: "Deny",
	"拖动 {0} 模块排序": "Drag {0} module to sort",
	拖动排序: "Drag to sort",
	拖动调整宽度: "Drag to adjust width",
	拖动调整宽高: "Drag to adjust width and height",
	拖动调整高度: "Drag to adjust height",
	"拖拽 .zip 文件到此处安装": "Drag and drop the .zip file here to install",
	拖拽到这里上传: "Drag and drop here to upload",
	指令: "Command",
	"指令…": "Command...",
	指标: "Indicators",
	按供应商: "By supplier",
	按供应商分类的模型: "Models by Supplier",
	"按修改时间（新到旧）": "By modification time (newest to oldest)",
	按名称: "By name",
	"按工作流 input_params 传入": "Pass in input_params according to workflow",
	"按条件选择后续分支。": "Select subsequent branches conditionally.",
	按清单使用工具: "Use tools from list",
	按状态筛选: "Filter by status",
	按类型筛选: "Filter by type",
	按组: "By group",
	按组分类的模型: "Models by group",
	"按组新增模型时必须填写 API 基础 URL": "When adding a new model by group, the API base URL must be filled in",
	按角色筛选: "Filter by role",
	"按计划运行任务，或在需要时随时执行。": "Run the task on a schedule, or execute it anytime when needed.",
	"换个关键词再试。": "Change the keyword and try again.",
	换个关键词试试: "Try changing the keywords",
	排队: "Queuing",
	消息发送: "Message sending",
	直接引导: "Guide directly",
	"Enter 发送方式": "Enter key behavior",
	"打开时直接按 Enter 会把消息立即交给当前回合；关闭时直接按 Enter 先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种。会话空闲时两个键都开新回合，两个键都不会改动已排队的项。": "When on, pressing Enter hands the message to the current turn immediately; when off, Enter puts it in the input queue and it is sent in order after the current turn ends. Ctrl+Enter always does the other one. When the session is idle both keys start a new turn, and neither key touches items already queued.",
	"Enter 直接引导": "Enter guides directly",
	"当前：Enter 直接引导，Ctrl+Enter 排队": "Now: Enter guides directly, Ctrl+Enter queues",
	"当前：Enter 排队，Ctrl+Enter 直接引导": "Now: Enter queues, Ctrl+Enter guides directly",
	"会话正在运行时发送消息的去向：直接引导会把消息立即交给当前回合；排队会先进入输入队列，本轮结束后按顺序发出。Ctrl+Enter 永远执行另一种，且两个键都不会改动已排队的项。": "Where a message goes while a session is running: Guide directly hands it to the current turn immediately; Queue holds it in the input queue and sends it in order after the current turn ends. Ctrl+Enter always does the other one, and neither key touches items already queued.",
	"排队项，可拖拽调整顺序": "Queued item, drag to reorder",
	拖拽调整顺序: "Drag to reorder",
	"排队失败：{0}": "Queuing failed: {0}",
	"排除的默认上下文文件（except）": "Excluded default context file (except)",
	接口类型: "Interface type",
	接口类型与适配参数: "Interface type and adaptation parameters",
	"接收 {0} 消息失败": "Failed to receive {0} message",
	"接收工作流输入。": "Receive workflow input.",
	控件: "Control",
	控制: "Control",
	"控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。": "Default scope for controlling file operations; higher risk rules are still enforced by Sunday.",
	"控制新会话的默认权限；当前任务可以在输入框中临时调整。": "Controls the default permissions for new sessions; the current task can be temporarily adjusted in the input box.",
	"控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。": "Control which tools are visible to the model and how the tools are exposed in think/execution mode.",
	"控制过程行前的常规、运行与完成图标；等待和错误仍使用状态色。": "Control the normal, run and complete icons in front of process lines; wait and error still use status colors.",
	推理: "Reasoning",
	推理预算: "Inference budget",
	"描述（description）": "description",
	提交: "Submit",
	"提交中…": "Submitting...",
	"提交数据必须是 JSON 对象": "Submitted data must be a JSON object",
	"提交数据必须是有效 JSON": "Submitted data must be valid JSON",
	"提交数据（JSON）": "Submit data (JSON)",
	提示文本: "Prompt text",
	提示文本不能为空: "Prompt text cannot be empty",
	提问: "Ask a question",
	提问自动继续: "Question continues automatically",
	插件: "Plugins",
	"插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件可禁用、不可卸载；每个插件按平台分类（通用 / 桌面端专用 / 移动端专用），本机只列出适用的部分。": "Plug-in = unified installation unit of Tools/Skills/Hooks/MCP. Built-in plug-ins can be disabled and cannot be uninstalled; each plug-in is classified by platform (universal/desktop-specific/mobile-specific), and only the applicable parts are listed here.",
	"插件与 MCP": "Plugins and MCP",
	"插件与 MCP 的 hard block 不能从此页解除。": "The hard block of plug-ins and MCP cannot be released from this page.",
	更多插件: "More plugins",
	在分屏中打开: "Open in split view",
	在右侧分屏中打开: "Open in the right split",
	在下方分屏中打开: "Open in the bottom split",
	插件分区: "Plug-in partition",
	插件功能不可用: "Plug-in function is not available",
	插件未返回有效数据: "The plug-in did not return valid data",
	"插件目录或 .zip 路径": "Plugin directory or .zip path",
	"插值）": "Interpolation)",
	"插入 Callout": "Insert Callout",
	"插入 Mermaid 图": "Insert Mermaid Diagram",
	插入代码块: "Insert code block",
	插入公式: "Insert formula",
	插入引用: "Insert reference",
	插入表格: "Insert table",
	搜索: "Search",
	"搜索 {0}": "Search {0}",
	"搜索不可用：{0}": "Search not available: {0}",
	"搜索中…": "Searching...",
	"搜索了{0}次": "Searched {0} times",
	"搜索了{0}次…": "Searched {0} times...",
	"搜索任务、插件或文件": "Search for tasks, plugins or files",
	搜索供应商: "Search for suppliers",
	搜索内容: "Search content",
	"搜索名称、分类或说明": "Search name, category or description",
	"搜索名称、路径或来源…": "Search name, path or source...",
	搜索工作区索引: "Search workspace index",
	搜索工具: "Search tool",
	搜索成果库: "Search results library",
	"搜索插件未启用。到「插件」页启用 websearch 后可用。": "Search plugin is not enabled. It is available after enabling websearch on the \"Plugins\" page.",
	搜索服务响应正常: "Search service responds normally",
	搜索模型: "Search model",
	搜索模型组: "Search model group",
	搜索模式: "Search mode",
	搜索结果: "Search results",
	搜索节点: "Search node",
	搜索范围: "Search scope",
	搜索记忆: "Search memory",
	搜索资料库: "Search library",
	搜索项目: "Search items",
	搜索项目和会话: "Search projects and sessions",
	撤回: "Withdraw",
	撤销: "Undo",
	撤销后设备立即失去访问权限: "Device immediately loses access after revoking",
	"撤销（Ctrl/Cmd+Z）": "Undo (Ctrl/Cmd+Z)",
	操作: "Operation",
	操作失败: "Operation failed",
	"操作失败：{0}": "Operation failed: {0}",
	支持推理: "Support inference",
	"支持注释（JSONC），保存后即时生效。": "Supports comments (JSONC), which will take effect immediately after saving.",
	"收到了 {0} 的消息": "Message received from {0}",
	收藏: "Collection",
	"收藏：{0}": "Collection: {0}",
	收起: "Collapse",
	"收起 ": "Collapse",
	"收起 {0}": "Collapse {0}",
	收起会话: "Collapse session",
	收起计划: "Collapse plan",
	收起运行详情: "Collapse run details",
	放大: "Zoom in",
	放大对话: "Zoom in on a conversation",
	放弃: "Give up",
	放弃修改: "Abandon modification",
	"放弃未保存的修改？": "Discard unsaved changes?",
	放弃本地修改并采用远端版本: "Abandon local modifications and adopt remote version",
	"敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。": "Writing and editing of sensitive paths (e.g. .env, SSH credentials) still blocks.",
	教学示意图: "Teaching diagram",
	教学配图: "Teaching pictures",
	数据: "Data",
	整理: "Organize",
	文件: "File",
	"文件 {0}": "File {0}",
	"文件 · ": "File ·",
	文件名: "file name",
	"文件名（如 TEAM_RULES.md）": "File name (such as TEAM_RULES.md)",
	文件夹: "Folder",
	文件夹名: "Folder name",
	文件夹名称: "Folder name",
	文件改动: "File changes",
	"文件结束 · ": "End of file ·",
	文件缺失: "File missing",
	文件边界: "File boundaries",
	文本: "Text",
	文本操作: "Text actions",
	文本记录: "Text record",
	文本颜色: "Text color",
	"文本（不支持图片）": "Text (images not supported)",
	文档: "Documentation",
	文档大纲: "Document Outline",
	文档知识: "Documentation knowledge",
	斜体: "italic",
	新任务: "New task",
	新会话将从这里开始: "New session will start here",
	新会话默认: "New session default",
	"新供应商需要填写名称和 API Key": "New supplier needs to fill in name and API Key",
	新增: "New",
	"新增 Hook": "Add new Hook",
	"新增 {0} 行": "Added {0} rows",
	"新增一个模式后，就可以设置它能使用的工具。": "After adding a new mode, you can set the tools it can use.",
	新增供应商: "Add new supplier",
	新增模型: "Add new model",
	新增模式: "New mode",
	新增第一条角色分配: "Add the first role assignment",
	新增触发器: "Add new trigger",
	新建: "New",
	新建任务: "Create new task",
	新建会话: "New conversation",
	新建定时任务: "Create a new scheduled task",
	新建工作流: "Create new workflow",
	新建技能: "Create new skill",
	新建文件夹: "Create new folder",
	"新建文件夹…": "Create new folder...",
	新建方案: "Create new scheme",
	新建模型组: "Create a new model group",
	新建节点: "Create new node",
	新建记忆: "Create new memory",
	新建项目: "New project",
	方案: "Plans",
	方案传输: "Scheme transfer",
	方案名称: "Scheme name",
	"方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态": "The plan can't be started until the plan is ready - Say \"It's ready to start\" to the assistant in chat and it will update the plan status",
	方案编辑: "Scheme editing",
	方案阅读: "Scheme Reading",
	无依赖: "No dependencies",
	无多模态模型: "No multimodal model",
	无工具: "No tool",
	无序列表: "Unordered list",
	无技能: "No skills",
	"无法创建模型组 {0}": "Unable to create model group {0}",
	"无法打开学习会话，请重试": "Unable to open learning session, please try again",
	"无法打开：{0}": "Unable to open: {0}",
	无法显示: "Unable to display",
	"无法更新连线：端口类型不兼容或端口不存在": "Unable to update connection: port type is incompatible or port does not exist",
	"无法读取文本：{0}": "Unable to read text: {0}",
	"无法连接服务器：{0}": "Unable to connect to server: {0}",
	"无法连接：端口类型不兼容或端口不存在": "Unable to connect: Incompatible port type or port does not exist",
	无钩子: "No hook",
	无需压缩: "No compression required",
	日: "Day",
	日出渐变: "Sunrise gradient",
	日历: "Calendar",
	日历触发器需要时间: "Calendar trigger takes time",
	日历频率: "Calendar frequency",
	日志: "Log",
	日期: "Date",
	时区: "Time zone",
	时间: "Time",
	"时间 {0}": "Time {0}",
	映射: "Mapping",
	"显式替换现有激活，并固定到当前 revision": "Explicitly replace existing activation and pin to current revision",
	显示名称: "Display name",
	显示已移除: "Display removed",
	显示更早的过程: "Show older processes",
	显示模块: "Display module",
	晨会摘要: "Morning meeting summary",
	晨宵: "Morning and evening",
	智能: "Intelligence",
	智能体: "Agent",
	"智能体目标…": "Agent target...",
	"暂不可用：{0}": "Temporarily unavailable: {0}",
	暂停: "Pause",
	"暂停工作流，等待人工批准或拒绝。": "Workflow paused pending manual approval or rejection.",
	暂无: "None yet",
	暂无上下文: "No context yet",
	暂无上下文统计: "No contextual statistics yet",
	暂无会话: "No session yet",
	"暂无内容，创建一个开始。": "No content yet, create one to start.",
	"暂无可显示的 Sub Agent 事件。": "There are no Sub Agent events to display.",
	暂无可添加的模型: "There are no models to add yet.",
	暂无可用工具: "No tools available yet",
	暂无可用数据: "No data available yet",
	暂无可用模型: "No model available yet",
	"暂无可用模型，可手动输入模型 ID": "No model available yet, you can enter the model ID manually",
	暂无已登记项目: "No registered projects yet",
	"暂无已登记项目。": "There are no registered projects yet.",
	"暂无已移除的成果。": "No results have been removed yet.",
	暂无待处理任务: "No pending tasks yet",
	"暂无消息，发送一个任务。": "No message yet, send a task.",
	"暂无笔记关系。": "There is no note relationship yet.",
	"暂无符合筛选条件的成果。": "There are currently no results that meet the filter criteria.",
	暂无节点: "No node yet",
	"暂无触发器。新增后可配置手动或定时入口。": "No trigger yet. After adding, manual or scheduled entrance can be configured.",
	"暂无资源统计。": "No resource statistics yet.",
	"暴露为 Agent 工具": "Exposed as Agent tool",
	更多: "More",
	更新: "Update",
	"更新 v{0} 已下载并校验，点击安装": "Update v{0} has been downloaded and verified, click to install",
	更新于: "Updated on",
	更新任务清单: "Update task list",
	更新定时任务失败: "Failed to update scheduled task",
	"更新模型标识、能力和运行参数。": "Update model identification, capabilities and operating parameters.",
	更新计划: "Update plan",
	"更新连接信息，已有密钥不会被覆盖。": "Update connection information, existing keys will not be overwritten.",
	替换并激活: "Replace and activate",
	最低思考强度: "Minimum thinking intensity",
	"最低思考强度 {0}": "Minimum thinking intensity {0}",
	最后一个: "Last",
	最多运行次数: "Maximum number of runs",
	最大化: "Maximize",
	最大并发: "Maximum concurrency",
	最大输出: "Maximum output",
	最大运行次数: "Maximum number of runs",
	"最大运行次数（可选）": "Maximum number of runs (optional)",
	最大迭代: "Maximum iterations",
	最小化: "Minimize",
	"最小间隔（秒）": "Minimum interval (seconds)",
	最新版本: "latest version",
	最近: "Recent",
	"最近一次 {0}": "Most recent {0}",
	最近任务: "Recent tasks",
	最近打开: "Recently opened",
	最近项目: "Recent projects",
	最高思考强度: "Highest thinking intensity",
	"最高思考强度 {0}": "Highest thinking intensity {0}",
	有序列表: "Ordered list",
	有效期至: "Valid until",
	有新版本可用: "A new version is available",
	有未保存修改: "There are unsaved modifications",
	有未保存的修改: "There are unsaved changes",
	服务器: "Server",
	"服务器地址必须使用 HTTP 或 HTTPS": "Server address must use HTTP or HTTPS",
	服务器地址格式无效: "Invalid server address format",
	"服务器未返回有效的桌面 Node": "Server did not return a valid desktop Node",
	"服务器请求失败（{0}）": "Server request failed ({0})",
	服务器账号: "Server account",
	服务器返回了无效的登录凭据: "The server returned invalid login credentials",
	服务地址: "Service address",
	未上报: "Not reported",
	未上报缓存: "Cache not reported",
	未保存: "Not saved",
	未关联供应商: "Supplier not associated",
	未分组: "Not grouped",
	"未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。": "No Hook found. Click \"Add Hook\" to create an event hook, or switch to \"Original Configuration\" to write JSON by hand.",
	"未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为": "No Skill found. Click \"New Skill\" to create, or put SKILL.md into the skill directory (for desktop",
	未发现新目录: "No new directory found",
	未启用: "Not enabled",
	未命中: "Missed",
	未命名定时任务: "Unnamed scheduled task",
	未命名工作流: "Unnamed workflow",
	未命名来源: "Unnamed source",
	未命名节点: "Unnamed node",
	未命名运行: "Unnamed run",
	未命名项目: "Unnamed item",
	"未安装 RAG 插件；可尝试兼容搜索": "RAG plug-in not installed; try compatibility search",
	未找到匹配的项目或会话: "No matching project or session found",
	"未找到对应笔记，无法导航。": "The corresponding note was not found and cannot be navigated.",
	"未找到该消息（可能已被删除或属于子会话）": "The message was not found (may have been deleted or belongs to a subsession)",
	"未找到：{0}": "Not found: {0}",
	未指定: "Not specified",
	未提供命令: "No command provided",
	"未提取到正文摘要。": "The text summary was not extracted.",
	未检查: "Not checked",
	未激活: "Not activated",
	未登录: "Not logged in",
	未知: "Unknown",
	未知命令: "Unknown command",
	未知触发方式: "Unknown trigger method",
	未获取: "Not obtained",
	"未获得收益 · ": "No benefit received ·",
	"未记录任务内容。": "Task content not recorded.",
	未设置事件: "Event not set",
	未设置时间: "Time not set",
	"未设置（可在设置中调整）": "Not set (can be adjusted in settings)",
	未运行: "Not running",
	未连接到搜索服务: "Not connected to search service",
	未选择: "Not selected",
	未配置: "Not configured",
	"未配置（使用内置兜底：{0}）": "Not configured (using built-in cover: {0})",
	"未回答的子代理提问 {count} 个": "{count} unanswered sub-agent question(s)",
	未完成的步骤: "the unfinished step",
	"本地 zip 路径": "Local zip path",
	本地目录: "Local directory",
	本机: "Native",
	"本机命令工具使用的 shell": "Shell used by native command tools",
	本机身份: "Native identity",
	本轮产出: "Output of this round",
	"机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。": "When the current round is interrupted due to insufficient machine memory, Sunday will explain the reason and state \"Automatically continue when the available memory is greater than the available memory\"; after the memory is restored, a new round will be automatically opened in the same session and continued, up to 3 times in a row. It will no longer automatically continue when you send a new message first.",
	权限: "Permissions",
	"权限偏好保存失败：{0}": "Failed to save permission preferences: {0}",
	权限审批: "Permission approval",
	"权限审批与输入框保持一致；工具清单由“工具模式”管理。": "Permission approval is consistent with the input box; the tool list is managed by \"Tool Mode\".",
	权限审批选项: "Permission approval options",
	"权限模式保存失败，已回滚：{0}": "Permission mode save failed, rolled back: {0}",
	条件: "Condition",
	条关系: "relationship",
	条用户指令: "User command",
	来源: "Source",
	来自子代理: "From subagent",
	松开以安装: "Release to install",
	松开鼠标上传附件: "Release the mouse to upload attachments",
	极光渐变: "Aurora gradient",
	极高: "Maximum",
	构建稳定的工作流程: "Build a stable workflow",
	查看: "View",
	"查看 git 差异": "View git diffs",
	"查看 git 状态": "View git status",
	查看全文: "View full text",
	"查看其余 ": "View the rest",
	"查看其余 {0} 步": "View remaining {0} steps",
	查看发布说明: "View release notes",
	查看官方文档: "View official documentation",
	标准: "Standard",
	标准输出: "standard output",
	标记: "Mark",
	标题: "Title",
	"标题（name）": "title (name)",
	框架: "Frame",
	"框架.{0}": "Frame.{0}",
	桌面端专用: "Desktop only",
	"档位 全局档": "gear global file",
	"档位 项目档": "File project file",
	"检查中…": "Checking...",
	"检查失败：": "Check failed:",
	检查更新: "Check for updates",
	"检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。": "Check the code and data changes in the last 24 hours, identify risks such as running errors, data loss, and permission violation, and attach code locations and repair suggestions.",
	检查连接: "Check connection",
	"检测到版本冲突，但无法读取远端版本：{0}": "Version conflict detected, but remote version cannot be read: {0}",
	"检测到版本冲突，远端版本暂不可读取": "Version conflict detected, the remote version is temporarily unreadable",
	森林渐变: "Forest gradient",
	棱镜渐变: "Prismatic Gradient",
	模型: "Model",
	"模型 ID": "Model ID",
	"模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。": "The export traffic of models, MCP, command tools, web crawling and searching, plug-in installation, and software update downloads will all go through this proxy; the web pages (rendering layer) in the application interface follow the system proxy settings. When left blank, these flows are connected directly and system environment variables are not read. The local address (localhost, 127.0.0.1, ::1) is always directly connected.",
	模型与供应商: "Models",
	"模型与供应商、外观主题、工具权限等应用配置。": "Configure models, appearance, tool permissions, and other app settings.",
	模型与思考参数: "Models and Thinking Parameters",
	"模型与思考强度：{0} {1}": "Model and thinking intensity: {0} {1}",
	模型分类方式: "Model classification method",
	"模型分类方式保存失败，已回滚：{0}": "The model classification method failed to save and has been rolled back: {0}",
	"模型列表加载失败，可手动输入": "The model list failed to load, you can enter it manually",
	"模型可同时存在于多个组；删除组不会删除模型。": "Models can exist in multiple groups at the same time; deleting a group does not delete the model.",
	模型已创建并加入分组: "The model has been created and added to the group",
	模型已删除: "Model deleted",
	模型已更新: "Model updated",
	模型已添加: "Model added",
	"模型指令…": "Model command...",
	模型数量: "Number of models",
	模型组: "Model group",
	模型组列表: "Model group list",
	模型组已创建: "Model group created",
	模型组已删除: "Model group deleted",
	模型组已更新: "Model group updated",
	模型组成员: "Model group members",
	模型组成员已更新: "Model group members updated",
	模型组空状态: "Model group empty status",
	模型组详情: "Model group details",
	模型能力: "Model capabilities",
	模型选项: "Model options",
	模型配置: "Model configuration",
	模式: "Mode",
	模式名: "Schema name",
	"模式名不能为空，已取消保存": "Schema name cannot be empty, saving canceled",
	"模式名重复：{0}，已取消保存": "Duplicate schema name: {0}, saving canceled",
	模式说明: "Mode Description",
	模板: "Template",
	模板入口: "Template entry",
	横向分布: "Horizontal distribution",
	横向滚动表格: "Horizontal scrolling table",
	橙色: "Orange",
	次: "times",
	次数: "times",
	"次调用 ·": "calls ·",
	"欢迎使用 Sunday": "Welcome to Sunday",
	正在: "Currently",
	"正在下载 v{0}…": "Downloading v{0}...",
	"正在下载…": "Downloading...",
	正在下载更新: "Downloading updates",
	"正在保存…": "Saving...",
	"正在保存项目更改…": "Saving project changes...",
	"正在停止…": "Stopping...",
	"正在准备完整归档，请稍候…": "Preparing complete archive, please wait...",
	"正在创建…": "Creating...",
	正在刷新进程列表: "Refreshing process list",
	"正在加载…": "Loading...",
	正在加载历史消息: "Loading historical messages",
	"正在加载工具模式…": "Loading tool mode...",
	"正在加载成果库…": "Loading results library...",
	正在加载更早消息: "Loading older messages",
	"正在加载笔记…": "Loading notes...",
	正在压缩上下文: "Compressing context",
	正在同步: "Synchronizing",
	"正在回答…": "Answering...",
	正在处理: "Processing",
	"正在安装…": "Installing...",
	正在安装更新: "Installing updates",
	"正在打开…": "Opening...",
	"正在检查…": "Checking...",
	"正在生成配对码…": "Generating pairing code...",
	"正在读取 Sub Agent 记录...": "Reading Sub Agent records...",
	"正在读取…": "Reading...",
	"正在读取后台进程…": "Reading background process...",
	"正在读取定时任务…": "Reading scheduled tasks...",
	"正在读取文本…": "Reading text...",
	"正在读取记忆…": "Reading memory...",
	"正在读取资料库…": "Loading library…",
	"正在读取项目…": "Reading items...",
	正在输出: "Outputting",
	正常: "normal",
	正文: "Text",
	"正在运行或已暂停的子代理 {count} 个": "{count} running or paused sub-agent(s)",
	此容器: "This container",
	"此操作不可撤销，将": "This operation cannot be undone and will",
	"此文件将交给系统默认应用处理。": "This file will be handed over to the system default application for processing.",
	此模块暂不可用: "This module is temporarily unavailable",
	此模块未启用: "This module is not enabled",
	此电脑: "This computer",
	此节点: "This node",
	此节点暂不支持可视化配置: "This node does not currently support visual configuration",
	步: "Step",
	步骤: "Steps",
	"步：": "Step:",
	每: "Every",
	"每 {0} 秒": "Every {0} seconds",
	每天: "Every day",
	"每天 {0}": "Every day {0}",
	每月: "Monthly",
	"每月 {0} 日 {1}": "{0} day {1} of every month",
	"每月日期必须是 1 到 31": "Monthly day must be 1 to 31",
	每月第几天: "Day of the month",
	每次新建: "New each time",
	每行一个: "one per line",
	"每隔（秒）": "every (seconds)",
	水平居中: "Center horizontally",
	"汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。": "Summarize the session progress, completed items, and items to be followed up since yesterday, and generate an oral summary of no more than 6 items. Read-only analysis, no changes to the file.",
	汇聚: "Join",
	"汇聚具名输入并收集为对象。": "Aggregate named input and collect into objects.",
	"没有匹配「{0}」的结果 — 换个关键词，或切到「全部」看看其他范围": "No results matching \"{0}\" — change the keyword, or switch to \"All\" to see other ranges",
	没有匹配的供应商: "No matching supplier",
	没有匹配的模型: "No matching model",
	没有匹配的模型组: "No matching model group",
	没有匹配的模式: "No matching pattern",
	没有匹配的节点: "No matching node",
	没有匹配的项目: "No matching items",
	没有匹配结果: "No matching results",
	没有可切换的插件模式: "No plug-in mode to switch to",
	没有找到匹配的工具: "No matching tool found",
	没有正在登记的后台进程: "No background process being registered",
	没有长期后台进程: "No long-term background process",
	"注入优先级（越小越靠前）": "Injection priority (the smaller the higher the priority)",
	注入到上下文的提示文本: "Tip text injected into context",
	注册: "Register",
	注释: "Comment",
	"注释.{0}": "Comment.{0}",
	浅色: "light color",
	浅色从: "light color from",
	"浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。": "The light color uses ivory white to carry the graphite mark, and the dark color is reversed to a graphite base and ivory mark.",
	"浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。": "Use fog blue to cream white for light colors, dark green to blue-black background for dark colors, and keep other interface layers neutral.",
	浅色开始时间: "Light color start time",
	测试: "Test",
	测试失败: "Test failed",
	测试超时: "Test timed out",
	测试通过: "Test passed",
	浏览: "Browse",
	"浏览…": "Browse...",
	"浏览了{0}个目录": "{0} directories browsed",
	"浏览了{0}个目录…": "{0} directories browsed...",
	浮梦: "Floating Dreams",
	海洋渐变: "Ocean Gradient",
	消息附件: "Message attachment",
	淡灰: "light gray",
	深色: "Dark",
	深色从: "Dark color from",
	深色开始时间: "Dark start time",
	添加: "Add",
	"添加一个 OpenAI Compatible 或其他模型供应商": "Add an OpenAI Compatible or other model provider",
	添加一条简短说明: "Add a short description",
	添加供应商: "Add supplier",
	添加到: "Add to",
	添加到当前会话: "Add to current session",
	添加到收藏: "Add to Favorites",
	添加到文件夹: "Add to folder",
	添加已有模型: "Add existing model",
	添加模型: "Add model",
	"添加现有模型，或创建一个新模型": "Add an existing model, or create a new one",
	"添加节点…": "Add node...",
	"添加节点：{0}": "Add node: {0}",
	添加计划: "Add plan",
	添加附件: "Add attachment",
	清单: "List",
	清理历史: "Clear history",
	"清理失败：{0}": "Cleanup failed: {0}",
	清空全部: "Clear all",
	清除: "Clear",
	"清除“全部工具”后，可以单独选择需要开放的工具。": "After clearing \"All Tools\", you can individually select the tools that need to be opened.",
	清除搜索: "Clear search",
	清除节点目录搜索: "Clear node directory search",
	渐变角度: "Gradient angle",
	温度: "Temperature",
	激活: "Activate",
	"激活会固定当前工作流 revision": "Activation will pin the current workflow revision",
	"激活失败：{0}": "Activation failed: {0}",
	"激活状态刷新失败：{0}": "Activation status refresh failed: {0}",
	"灰线：未上报缓存": "Gray line: cache not reported",
	灰色区压缩: "Gray area compression",
	灵感构思: "Inspirational Ideas",
	"点击“生成配对码”开始配对。": "Click \"Generate Pairing Code\" to start pairing.",
	"点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。": "Click the option to submit directly; you can also write down your handling method, press Enter or click \"Send\".",
	"点此申请 API key": "Click here to apply for API key",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。": "Then follow the execute-plan process to load the goals and steps into the list of the current session, and then start work step by step.",
	"然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工；方案文件的更新写回它原来的位置。": "Then follow the execute-plan process to load the goals and steps into the list of the current session, and then gradually start work; the update of the plan file is written back to its original location.",
	版本不符: "Version mismatch",
	版本信息: "Version information",
	"版本；切换后立即生效。": "Version; effective immediately after switching.",
	状态: "Status",
	"状态消息 (可选)": "Status message (optional)",
	"状态：{0}": "Status: {0}",
	生图: "Raw pictures",
	"生成 {0}": "Generate {0}",
	生成中: "Generating",
	生成图片: "Generate image",
	生成工具输入: "Generate tool input",
	生成配对码: "Generate pairing code",
	"用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。": "Use LamTools mobile to view conversations, continue tasks, and process approvals. Core still only listens to local addresses.",
	用一句话说明要怎么处理: "Explain in one sentence what to do",
	"用于侧边栏中的项目辨识。": "Used for item identification in the sidebar.",
	用户: "User",
	用户上传: "User upload",
	用户名: "Username",
	用户指令导航: "User command navigation",
	用户消息: "User message",
	电脑: "Computer",
	画布元素: "Canvas element",
	画布元素操作: "Canvas element operations",
	画布布局工具: "Canvas layout tool",
	界面: "Appearance",
	界面密度: "Interface Density",
	界面语言: "Interface language",
	留空不限: "No limit to leaving blank",
	留空以保留现有密钥: "Leave blank to retain existing key",
	留空时使用目录名称: "Use directory name when left empty",
	"留空时直连；填写后使用 http://127.0.0.1:端口。": "Direct connection when left blank; use http://127.0.0.1: port after filling in.",
	登录: "Login",
	"登录 / 账号": "Login/Account",
	"登录后在手机上配对，这里会列出已配对的设备。": "After logging in, pair on the phone. The paired devices will be listed here.",
	"登录状态与已配对的设备。": "Login status with paired device.",
	的: "of",
	"的模型。": "Model of .",
	"目录 ": "Directory",
	"目录名 + frontmatter name": "directory name + frontmatter name",
	"目录路径（工作区相对或绝对）": "Directory path (workspace relative or absolute)",
	目标: "Target",
	目标与待发送输入: "Target and input to be sent",
	相关设置: "Related settings",
	相册: "Photo album",
	相机: "Camera",
	知识关系: "Knowledge Relationships",
	知识图谱: "Knowledge Graph",
	知识层级: "Knowledge Hierarchy",
	知道了: "Got it",
	"确定删除“{0}”及其内部 {1} 个元素？此操作不可撤销。": "Are you sure you want to delete '{0}' and {1} elements inside it? This action cannot be undone.",
	确认: "Confirm",
	确认删除: "Confirm deletion",
	确认放弃修改: "Confirm to abandon modification",
	确认清理: "Confirm cleanup",
	确认清理队列: "Confirm cleanup queue",
	确认移除: "Confirm removal",
	"确认（{0}秒）": "Confirm ({0} seconds)",
	禁止: "Forbidden",
	"禁用技能 {0}": "Disabled skill {0}",
	"禁用插件 {0}": "Disable plugin {0}",
	离线: "Offline",
	秒: "seconds",
	移出组: "Move out of group",
	移动: "Move",
	移动端专用: "Mobile only",
	移动端快捷操作: "Quick operations on mobile terminal",
	移动设备: "Mobile device",
	移除: "Remove",
	"移除 {0}": "Remove {0}",
	移除计划: "Remove plan",
	移除记录: "Remove record",
	"移除进程 ": "Remove process",
	"空值表示无条件；表达式不满足时，下游会跳过。": "A null value means unconditional; when the expression is not satisfied, the downstream will be skipped.",
	空闲: "Idle",
	"窗口（秒）": "Window (seconds)",
	立即安装: "Install now",
	端口: "Port",
	笔记: "Notes",
	笔记关系图: "Note relationship diagram",
	笔记关联: "Note association",
	笔记助手: "Note Assistant",
	笔记库: "Note library",
	笔记总体关系图: "Overall relationship diagram of notes",
	笔记文件树: "Note file tree",
	笔记来源: "Note source",
	笔记节点: "Note node",
	第: "No.",
	"第 {0} / {1} 项": "Item {0}/{1}",
	"第 {0} 条用户指令，共 {1} 条": "User command {0} of {1} in total",
	"第 {0} 条角色分配必须选择建议模型。": "Role assignment {0} must select a proposed model.",
	"第 {0} 条角色分配的任务类型不能为空。": "The task type of role assignment {0} cannot be empty.",
	"第 {0} 条角色分配的最低思考强度不能高于最高思考强度。": "The minimum thinking intensity assigned to role {0} cannot be higher than the maximum thinking intensity.",
	"第 {0} 行": "Line {0}",
	"第 {0}/{1} 段": "Paragraph {0}/{1}",
	等待: "Waiting",
	等待中: "Waiting",
	等待事件: "Wait for event",
	等待你的选择: "Waiting for your choice",
	"等待外部事件后继续执行。": "Wait for external events before continuing execution.",
	等待选择: "Waiting for selection",
	等待回答: "Waiting for an answer",
	策略: "Strategy",
	"策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。": "The policy applies to workflow runs; restricted runs will enter a retryable pause state and do not occupy execution slots.",
	筛选资料: "Filter resources",
	筛选资料库: "Filter library",
	"管理 web_search 工具使用的搜索引擎内核与网络代理，保存到 websearch 插件配置后即时生效。": "Manage the search engine core and network proxy used by the web_search tool, which will take effect immediately after saving to the websearch plug-in configuration.",
	"管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。": "Management event hooks. Untrusted Hooks will not be executed and need to be enabled after this review.",
	管理你的知识: "Manage your knowledge",
	管理定时任务: "Manage scheduled tasks",
	"管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。": "Manage discovered Skills. After being disabled, they will not appear in the slash command; new skills are written to the user-level skills directory, and the Agent calls load_skill on demand.",
	"管理已安装的插件，开关它们带来的界面与工具。": "Manage installed plug-ins and switch the interfaces and tools they bring.",
	"管理模型接入、供应商配置与默认模型选择。": "Manage model access, supplier configuration and default model selection.",
	管理目标: "Management target",
	类型: "Type",
	"类型 {0}": "Type {0}",
	粉色: "Pink",
	粘贴: "Paste",
	"粘贴失败：当前环境无法读取剪贴板": "Paste failed: Clipboard cannot be read by the current environment",
	系统: "System",
	系统打开: "System open",
	"系统提示词…": "System prompt word...",
	索引可用: "Index available",
	索引异常: "Index exception",
	索引未检查: "Index not checked",
	紧凑: "Compact",
	紫色: "Purple",
	紫蓝渐变: "purple-blue gradient",
	红色: "red",
	纯文本: "Plain text",
	"纯色层级更安静，并以清晰实线边界维持长期工作的可读性。": "Solid color levels are quieter and maintain readability for long-term work with clear solid borders.",
	纵向分布: "Vertical distribution",
	终止进程: "Terminating process",
	"终止进程 ": "Terminating process",
	"终止这个回合？": "Terminate this turn?",
	结束: "End",
	结果: "Result",
	"结果上限 limit（默认 5，1-20）": "Result upper limit limit (default 5, 1-20)",
	结论: "Conclusion",
	"给 Sunday 发送任务...": "Send task to Sunday...",
	"继承全局策略：{0}": "Inherit global policy: {0}",
	"继承全局（当前：{0}）": "Inherit global (current: {0})",
	继续编辑: "Continue editing",
	"继续问…": "Keep asking...",
	绿色: "green",
	缓存: "Cache",
	缓存命中率: "Cache hit rate",
	"缓存（": "Cache (",
	编排: "Orchestration",
	编辑: "Edit",
	"编辑 {0}": "Edit {0}",
	编辑供应商: "Edit Supplier",
	编辑右侧面板布局: "Edit right panel layout",
	编辑定时任务: "Edit scheduled tasks",
	编辑工作流: "Edit workflow",
	编辑待发送内容: "Edit content to be sent",
	编辑文件: "Edit file",
	编辑条件: "Edit conditions",
	编辑模型: "Edit model",
	编辑消息: "Edit message",
	编辑笔记全文: "Edit the full text of the note",
	编辑节点: "Edit node",
	编辑连线条件: "Edit connection conditions",
	缩小: "Zoom out",
	缺少可打开的附件标识: "Missing openable attachment identifier",
	缺少可读取的文本路径: "Missing readable text path",
	网关: "Gateway",
	网关运行中: "Gateway is running",
	网格吸附已关闭: "Grid snapping is turned off",
	网格吸附已开启: "Grid snapping is on",
	网格视图: "Grid view",
	置顶: "Pinned",
	置顶会话: "Pinned conversation",
	置顶项目: "Pinned item",
	翻译: "Translation",
	耗时: "Time consuming",
	"耗时 ": "Time consuming",
	"耗时 {0} s": "Took {0} s",
	"耗时 —": "Time consuming —",
	聊天: "Chat",
	聚焦选中: "Focus selected",
	"背景板 / 侧边栏": "Background/Sidebar",
	能力: "Ability",
	能力分类: "Ability Classification",
	"能力的模型。保存到": "Model of capabilities. save to",
	自动: "Auto",
	自动检查: "Automatic check",
	"自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。": "Automatic mode selects available shells in the order WSL → Git Bash → PowerShell; it also falls back in this order when the manually selected shell is unavailable.",
	"自动继续的内存阈值（GB）": "Memory threshold for auto-continue (GB)",
	"自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。": "Memory threshold for automatic continuation (GB): available memory = physical memory + the amount that the page file can still allocate. Turning it up is more conservative, but it will take longer.",
	"自动（内置声明）": "Automatic (built-in declaration)",
	自定义: "Custom",
	"自定义工作流节点。": "Custom workflow node.",
	自定义接口: "Custom interface",
	自定义证书: "Custom certificate",
	自检: "Self-test",
	"自迭代 (loop)": "self-iteration (loop)",
	节流: "Throttling",
	"节流 {0}s": "Throttling {0}s",
	节点: "Node",
	"节点 {0} · 画布元素 {1}": "Node {0} · Canvas element {1}",
	节点分类: "Node classification",
	节点参数: "Node parameters",
	节点已对齐: "Nodes are aligned",
	节点已横向分布: "Nodes have been distributed horizontally",
	节点已纵向分布: "Nodes have been distributed vertically",
	节点标题: "Node title",
	节点目录: "Node directory",
	节点目录筛选: "Node directory filtering",
	"英 {0} 美 {1}": "UK {0} US {1}",
	"范围 {0}-{1} 行": "Range {0}-{1} rows",
	"范围进度，尚未独立评估": "Scope progress, not independently evaluated",
	草稿: "Draft",
	莓果渐变: "Berry Gradient",
	"莓紫、灰蓝与青绿的横向渐变。": "Horizontal gradient of raspberry purple, gray blue and turquoise.",
	获取网页: "Get web page",
	"获取网页 {0}": "Get web page {0}",
	蓝色: "blue",
	行: "OK",
	行内代码: "Inline code",
	"补齐缺少的端口（": "Complete missing ports (",
	表单说明: "Form description",
	表格: "Table",
	覆盖: "Overwrite",
	"规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。": "Rules will be appended uniformly after the sub_agent calls the discipline. When the task type matches, the main agent is provided with suggested sub-agent types, models and thinking intensity ranges.",
	视图切换: "View switching",
	视觉: "Vision",
	角色: "Role",
	角色分配: "Role assignment",
	解释: "Explanation",
	解锁: "Unlock",
	"解锁 {0}": "Unlock {0}",
	触发器: "Trigger",
	"触发器 ID 不能为空": "Trigger ID cannot be empty",
	"触发器 ID 已存在：{0}": "Trigger ID already exists: {0}",
	"触发器 {0}": "Trigger {0}",
	触发器列表: "Trigger list",
	"触发器已保存。": "Trigger saved.",
	触发器激活: "Trigger activated",
	触发器类型: "Trigger type",
	计划: "Planning",
	计划更新失败: "Scheduled update failed",
	"计划：{0} 步": "Plan: {0} steps",
	"让 agent 完成的目标…": "Let the agent complete the goal...",
	记忆: "Memory",
	记忆名称: "Memory name",
	"记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。": "Memories are just ordinary files: what you write here can be read by the assistant in every subsequent session.",
	记忆档位: "Memory gear",
	记忆续跑: "Memory continuation",
	记忆编辑: "Memory Editing",
	记忆阅读: "Memory Reading",
	设为预设首选: "Set as default preference",
	设备: "Device",
	"设备 ID": "Device ID",
	设备与工作环境: "Equipment and Work Environment",
	设置: "Settings",
	设置分区: "Set partition",
	"设置界面语言、网络连接与运行偏好。": "Configure the interface language, network connection, and runtime preferences.",
	设计创作: "Design Creation",
	询问: "Ask",
	该供应商下还没有模型: "There are no models under this supplier yet",
	该目录已在列表中: "The directory is already in the list",
	该组还没有模型: "There are no models for this group yet",
	该连线已经存在: "The connection already exists",
	详情: "Details",
	详细调整: "Detailed adjustments",
	"说明何时使用，供 Agent 检索": "Indicate when to use, for Agent to retrieve",
	"说明希望如何处理…": "Indicate how you would like to handle...",
	"请先保存工作流并解决冲突，再激活触发器": "Please save the workflow and resolve conflicts before activating the trigger",
	"请先新增供应商，再添加模型": "Please add a supplier first and then add a model",
	"请先添加供应商/模型（设置 → 模型与供应商）": "Please add a provider/model first (Settings → Models).",
	请先选择会话: "Please select a session first",
	请先选择供应商: "Please select a supplier first",
	"请填写必填输入：{0}": "Please fill in the required input: {0}",
	请求中: "Requesting",
	"请输入有效 JSON：{0}": "Please enter valid JSON: {0}",
	"请选择完整归档的保存位置…": "Please select a location to save the complete archive...",
	读: "Read",
	"读取 {0}": "Reading {0}",
	读取中: "Reading",
	"读取中…": "Reading...",
	"读取了{0}个文件": "{0} files read",
	"读取了{0}个文件…": "{0} files read...",
	读取失败: "Read failed",
	读取定时任务失败: "Failed to read scheduled task",
	读取文件: "Reading file",
	"读取运行记录…": "Reading running records...",
	"读取运行详情失败：{0}": "Failed to read run details: {0}",
	调度: "Scheduling",
	调度方式: "Scheduling method",
	调整主界面: "Adjust the main interface",
	"调整内容区的信息密度。": "Adjust the information density of the content area.",
	调整子代理面板宽度: "Adjust subagent panel width",
	调整宽高: "Adjust width and height",
	调整控件: "Adjust controls",
	"调整此任务的执行时间、指令和运行方式。": "Adjust the execution time, instructions, and running mode of this task.",
	调整背景板和侧边栏: "Adjust background panel and sidebar",
	调整输入栏: "Adjust input fields",
	调用: "Call",
	"调用 MCP 工具": "Call MCP tool",
	"调用一次 (none)": "Called once (none)",
	"调用了{0}个工具": "{0} tools called",
	"调用另一个工作流。": "Calling another workflow.",
	"调用智能体执行任务，可按需使用工具。": "Call the agent to perform tasks and use tools as needed.",
	"象牙白与石墨灰的纯色主题。": "Solid color theme of ivory white and graphite gray.",
	负责人: "Person in charge",
	"负责逐工具能力边界，不在这里重复配置。": "Responsible for defining tool capability boundaries and will not repeat the configuration here.",
	账号: "Account",
	账号与设备: "Accounts and Devices",
	"账号绑定命令将在桌面 Tauri 运行时启用。": "The account binding command will be enabled when desktop Tauri is running.",
	资料: "Resources",
	"资料 / 记忆 / 方案 — 一个入口三块内容。": "Resources / Memory / Plans — three sections in one place.",
	资料库: "Library",
	"资料库 › {0}": "Library › {0}",
	"资料库 › 资料": "Library › Resources",
	资料库分区: "Library sections",
	资料库还是空的: "The library is empty",
	资源: "Resources",
	超时: "Timeout",
	"超时 ": "Timeout",
	"超时 (秒)": "Timeout (seconds)",
	"超时秒数 timeout": "Timeout seconds timeout",
	"超时（秒）": "Timeout (seconds)",
	超高: "Extra high",
	跟随系统: "Follow the system",
	"跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。": "Memory shared across projects — the model reads it in session and you organize it here.",
	"跨项目查找会话、消息、方案与文件。": "Find sessions, messages, projects and files across projects.",
	路径: "path",
	跳过: "Skip",
	转到注册: "Go to registration",
	转换: "Conversion",
	"转换（兼容）": "Conversion (compatible)",
	轻: "Low",
	输入: "Input",
	"输入你的回答…": "Enter your answer...",
	"输入关键词搜索任务、插件或文件": "Enter keywords to search for tasks, plug-ins or files",
	"输入内容...": "Enter content...",
	"输入内容…": "Enter content...",
	"输入必须是对象：{0}": "Input must be an object: {0}",
	"输入必须是数字：{0}": "Input must be numeric: {0}",
	"输入必须是数组：{0}": "Input must be an array: {0}",
	输入栏: "Input field",
	"输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。": "\"Ask/Auto/Full Access\" in the input box is the real-time status of the current session; switching to Auto or Full Access will immediately release the pending approval operation.",
	输入端口: "Input port",
	输入端口类型: "Input port type",
	输入输出: "Input and output",
	输出: "Output",
	"输出工作流结果。": "Output workflow results.",
	"输出格式（文本说明，可选）": "Output format (text description, optional)",
	输出端口: "Output port",
	"输出端口 = JSON 字段（强制 JSON 输出）": "Output port = JSON field (force JSON output)",
	"输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）": "Output port = JSON key name (stdout is automatically split when it is JSON)",
	"输出端口 = 给同名变量赋值": "Output port = assign a value to a variable with the same name",
	输出端口类型: "Output port type",
	"输出预设的常量值。": "Output the preset constant value.",
	过程: "Process",
	过程图标颜色: "Process icon color",
	过程图标颜色十六进制值: "Process icon color hex value",
	运行: "Run",
	"运行 ID": "Run ID",
	"运行 {0}": "Running {0}",
	"运行一条 Shell 命令。": "Run a shell command.",
	运行与适配: "Operation and Adaptation",
	运行中: "Running",
	"运行中…": "Running...",
	运行事件: "Running event",
	运行历史: "Run history",
	运行命令: "Run command",
	运行失败: "Run failed",
	"运行失败：{0}": "Run failed: {0}",
	运行整个工作流: "Run the entire workflow",
	运行时: "Runtime",
	运行模式: "Run mode",
	运行模式与权限参数: "Running mode and permission parameters",
	"运行模式与权限：{0} · {1}": "Running mode and permissions: {0} · {1}",
	运行模式选项: "Run mode options",
	运行此节点: "Running this node",
	运行状态: "Running status",
	运行策略: "Run policy",
	运行结果: "Running results",
	"运行节点…": "Running node...",
	运行详情: "Operation details",
	运行输入: "Run input",
	"运行输入必须是 JSON 对象": "Run input must be a JSON object",
	"运行输入（JSON，可选）": "Run input (JSON, optional)",
	运行进度: "Running progress",
	运行链路: "Running link",
	返回: "Back",
	返回主会话: "Return to main session",
	返回主界面: "Back to main view",
	返回会话: "Return to session",
	"返回会话（Esc）": "Return to session (Esc)",
	返回列表: "Return to list",
	返回学习: "Return to study",
	返回对话: "Return to conversation",
	返回登录: "Return to login",
	还原: "Restore",
	"还没有 Markdown 笔记。": "There are no Markdown notes yet.",
	还没有供应商: "No supplier yet",
	"还没有内容。": "No content yet.",
	还没有定时任务: "There is no scheduled task yet",
	还没有工作模式: "No working mode yet",
	"还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。": "Not archived yet - \"Archive to Folder\" in the menu of the file card will appear here.",
	"还没有摘要 — 打开写第一段。": "No abstract yet - open to write first paragraph.",
	"还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。": "There is no favorite solution yet - \"Add to Favorites\" in the menu of the solution card.",
	还没有方案: "No plan yet",
	还没有模型组: "No model group yet",
	还没有运行历史: "No running history yet",
	"还没有运行记录。": "There is no running record yet.",
	还没有项目有记忆: "No project has memory yet",
	这一层还没有文件: "There is no file for this layer yet",
	这一行没有可打开的文件路径: "There is no openable file path at this line",
	"这个子代理还没有产生过程记录。": "This subagent has not generated process records.",
	这个文件夹还是空的: "This folder is still empty",
	"这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。": "This folder is still empty - click \"New Solution\" in the upper right corner and it will be created here.",
	"这个文件夹里还没有记忆文件。": "There are no memory files in this folder yet.",
	这个模式可以使用全部工具: "All tools can be used in this mode",
	"这个状态下暂无任务。": "There are no tasks in this state.",
	"这个状态下暂无方案。": "There is no solution in this state.",
	"这个账号还没有已登记设备。": "This account has no registered devices.",
	"这些信息用于连接模型服务。": "This information is used to connect to the model service.",
	"这些设置只作为新会话的起点，不会静默改变已经运行的任务。": "These settings only serve as a starting point for new sessions and do not silently change already running tasks.",
	这条消息没有可用的回合: "No rounds available for this message",
	"这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。": "This reference appears multiple times in the document and cannot be safely locked; please select it in the editing mode.",
	这片记忆还是空的: "This memory is still empty",
	"这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。": "There are no knowledge points to display here yet; let the AI build the knowledge network in the learning session first.",
	这里还没有子文件夹: "There are no subfolders here yet",
	进度: "Progress",
	进程日志: "Process log",
	进行中: "In progress",
	进阶: "Advanced",
	"远程图片仅在 Study 中显示：{0}": "Remote images are displayed only in Study: {0}",
	"远端工作流有更新，请处理冲突": "The remote workflow has been updated, please handle the conflict.",
	"连接一个可用的模型服务。": "Connect to an available model service.",
	连接信息: "Connection information",
	连接异常: "Connection exception",
	连线已更新: "Connection updated",
	迭代模式: "Iteration mode",
	"追加加载的文件（addition）": "Additional loaded file (addition)",
	退出条件: "Exit condition",
	"退出条件（Python 表达式）": "Exit condition (Python expression)",
	"退出码 ": "Exit code",
	"退出码 {0}": "Exit code {0}",
	退出账号: "Log out of account",
	"适合长时间处理任务与配置。": "Suitable for long-term processing tasks and configurations.",
	适应画布: "Fit to canvas",
	"选中文字后右键，即可解释、询问或翻译。": "Right-click after selecting the text to explain, ask or translate.",
	选填: "Optional",
	"选填，如限速、用途、注意事项等": "Optional, such as speed limit, purpose, precautions, etc.",
	"选填，留空时使用模型 ID": "Optional, use model ID if left blank",
	选择: "Select",
	"选择 {0}": "Select {0}",
	"选择一个工作目录，系统会为项目准备基础配置。": "Select a working directory and the system will prepare the basic configuration for the project.",
	"选择一个已登记的项目继续工作。": "Select a registered project to continue working.",
	"选择主题随系统变化、固定在一个模式，或按时段自动切换。": "Choose the theme to change with the system, be fixed in a mode, or automatically switch according to time periods.",
	选择供应商: "Select supplier",
	"选择官方模板，或手动填写服务信息。": "Select the official template, or fill in the service information manually.",
	选择工作模式: "Select working mode",
	"选择工作流 JSON 文件": "Select workflow JSON file",
	选择工作环境: "Select work environment",
	选择已有照片: "Select existing photo",
	选择已登记项目: "Select registered items",
	"选择应用界面的显示语言。不会更改对话内容或模型的回答语言。": "Choose the app’s display language. Conversation content and model response language stay unchanged.",
	选择或填写项目地址: "Select or fill in the project address",
	"选择或输入模型 ID": "Select or enter model ID",
	选择模型: "Select model",
	选择模型组: "Select model group",
	"选择模板后，按官方页面申请 API key；免费模型通常有额度或容量限制。": "After selecting a template, apply for an API key from the official page; free models usually have quota or capacity limits.",
	选择此目录: "Select this directory",
	选择目录: "Select directory",
	选择要放入: "Select to put",
	选择附件来源: "Select attachment source",
	选择项目: "Select item",
	"选择项目后查看成果库。": "View the results library after selecting a project.",
	选择项目目录: "Select project directory",
	透明度: "Transparency",
	"逐工具白名单、工具模式与扩展权限分别管理": "Manage tool whitelist, tool mode and extended permissions separately",
	通用: "General",
	通用文件夹: "Universal folder",
	通过对话创建笔记: "Create notes from conversations",
	速率限制: "Rate limiting",
	"遍历数组 (map)": "Traverse array (map)",
	配图: "Illustration",
	配对新设备: "Pairing a new device",
	配置: "Configuration",
	"配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。": "Configure sub_agent call prompt words to guide the main Agent how and when to delegate sub-Agents (model/mode, etc.).",
	"配置任务的执行时间、指令和运行方式。": "Configure the execution time, instructions and running mode of the task.",
	配置完成: "Configuration completed",
	配置文件: "Configuration file",
	配置模型供应商: "Configure model provider",
	采用远端版本: "Use remote version",
	重做: "Redo",
	"重做（Ctrl/Cmd+Shift+Z）": "Redo (Ctrl/Cmd+Shift+Z)",
	重合区域: "Overlapping area",
	"重合区域：": "Overlapping area:",
	重命名: "Rename",
	"重命名会话 {0}": "Rename session {0}",
	"重命名失败：{0}": "Rename failed: {0}",
	重命名方案: "Rename scheme",
	重命名模型组: "Rename model group",
	重新下载: "Redownload",
	重新显示首次引导: "Reshow first boot",
	重新检查: "Recheck",
	重试: "Try again",
	重试中: "Retrying",
	"重试中 {0}/{1}": "Retrying {0}/{1}",
	重试次数: "Number of retries",
	重连中: "Reconnecting",
	钩子: "Hook",
	钩子·已信任: "Hook·Trusted",
	链接: "Link",
	锁定选中内容: "Lock selection",
	错误处理: "Error handling",
	错误输出: "Error output",
	"长期驻留（轮次结束后继续运行）": "Long-term residence (continue running after the end of the round)",
	问题: "Problem",
	间隔: "Interval",
	间隔秒数: "Interval seconds",
	"间隔触发器需要 every_seconds": "Interval trigger requires every_seconds",
	"阈值需要是 0.5 到 1024 之间的数字（GB）": "Threshold needs to be a number between 0.5 and 1024 (GB)",
	"队列 ID": "Queue ID",
	队列与历史: "Queues and History",
	队列优先级: "Queue priority",
	"队列刷新失败：{0}": "Queue refresh failed: {0}",
	队列视图: "Queue view",
	队列运行详情: "Queue operation details",
	防抖: "Anti-shake",
	"防抖 {0}s": "Anti-shake {0}s",
	防抖模式: "Anti-shake mode",
	附件: "Attachment",
	"附件上传失败：{0}": "Attachment upload failed: {0}",
	附件预览失败: "Attachment preview failed",
	附件预览已读取: "Attachment preview has been read",
	降级输出: "Downgraded output",
	降级输出端口: "Downgrade output port",
	降级默认值: "Downgrade defaults",
	"限速 {0}/{1}s": "Speed limit {0}/{1}s",
	随轮次结束清理: "Clean up at the end of the round",
	隐藏已移除: "Hide removed",
	"雾蓝到奶油白的浅色渐变。": "Light gradient from fog blue to creamy white.",
	需压缩: "Compression required",
	需确认: "Confirmation required",
	需要你确认: "Need your confirmation",
	"需要你确认，共 {0} 项": "Need your confirmation, {0} items in total",
	青色: "cyan",
	面板: "Panel",
	音视频: "Audio and video",
	顶对齐: "Top alignment",
	项: "Item",
	项目: "Projects",
	"项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。": "The project-scope sub_agent configuration will override the global configuration. Leave blank to fall back to inherited global/built-in defaults.",
	"项目作用域的元信息与 AGENTS.md 指令。": "Project-scoped metainformation with AGENTS.md directives.",
	"项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。": "Project saves working directory, session and run configuration. You can also open a directory that has been used.",
	"项目列表不可用，无法进入项目记忆": "Project list is not available, project memory cannot be entered",
	项目名称: "Project name",
	项目图标: "Project icon",
	项目图标与颜色: "Project icons and colors",
	项目地址: "Project address",
	项目外观: "Project Appearance",
	"项目将保存在当前设备。": "The project will be saved on the current device.",
	"项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。": "The project has not been configured with overrides; after selecting the policy and saving, only the current project is written.",
	项目成果库: "Project results library",
	项目操作: "Project Operations",
	"项目文件和自动生成的 AGENTS.md 将存放在此目录。": "The project files and automatically generated AGENTS.md will be stored in this directory.",
	项目目录: "Project directory",
	项目规则: "Project Rules",
	项目记忆: "Project memory",
	"项目记忆按项目归档 — 先选一个项目，再整理它的记忆。": "Project memories are archived by project - first select a project and then organize its memories.",
	项目设置: "Project settings",
	项目设置分区: "Project settings partition",
	"项目里进出的文件 — 用户上传、中间产物与最终产物。": "Files in and out of the project—user uploads, intermediate products, and final products.",
	项目颜色: "Item color",
	"项；文件本身不会被删除。": "Item; The file itself will not be deleted.",
	预览: "Preview",
	"预览 {0}": "Preview {0}",
	预览排版: "Preview layout",
	预设颜色: "Default color",
	预设首选: "Default preference",
	频率: "Frequency",
	颜色: "color",
	"颜色节点、透明度与界面密度": "Color nodes, transparency and interface density",
	风险扫描: "Risk Scan",
	首个执行: "First execution",
	首次任务: "First mission",
	首次使用引导: "First time boot",
	验证: "Verification",
	验证未通过: "Authentication failed",
	高: "High",
	"高危命令默认需要运行前确认（自动批准模式除外）。": "High-risk commands require confirmation before running by default (except in automatic approval mode).",
	高级工具白名单: "Advanced Tools Whitelist",
	高级设置: "Advanced settings",
	高级调整: "Advanced adjustments",
	"高级适配 JSON": "Advanced Adaptation JSON",
	"高级适配 JSON 必须是对象": "Advanced Adaptation JSON must be an object",
	默认: "Default",
	"默认值（空=哨兵跳过）": "Default value (empty = sentinel skipped)",
	"默认内核 provider": "Default kernel provider",
	默认多模态解析模型: "Default multimodal parsing model",
	"默认审批策略保存失败，已回滚：{0}": "The default approval policy failed to save and has been rolled back: {0}",
	默认搜索内核: "Default search kernel",
	默认模型: "Default model",
	"（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。 外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。": "(Domestic reachable, recommended) · bing (English/normal participle words available) · ddg (overseas spare tire). External tools (independent processes such as GPL/AGPL) are accessed via subprocess/http and need to manually configure JSONC.",
	"（支持": "(Supported",
	"（无）": "(none)",
	"（日志为空）": "(Log is empty)",
	"（暂无日志输出）": "(No log output yet)",
	"（检查网络后重试）": "(Check the network and try again)",
	"（空指令）": "(empty command)",
	"（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。": "(Unified configuration directory). Please edit project-level rules in \"Project Settings → Project\", and the two will be added together to inject system prompt words.",
	"（还没有内容）": "(no content yet)",
	"（还没有摘要）": "(no summary yet)",
	"（默认 work_root）": "(default work_root)",
	"（默认模型）": "(default model)",
	"＋ 新增模型": "+ Add new model",
	"＋ 新建供应商": "+ Create new supplier",
	"＋ 追加文件": "+ append file",
	"，且无法恢复。": ", and cannot be restored.",
	"，但没有适用于本平台的安装包（可到发布页查看）": ", but there is no installation package suitable for this platform (you can check it on the release page)",
	"，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：": ", globally overlays to each workspace (the workspace's own load_context.jsonc overlays on top of it). CLI:",
	"，移动端为应用私有技能目录）。": ", the mobile terminal is the application private skill directory).",
	"，里面的条目也会一起删掉": ", the entries inside will also be deleted together.",
	"：暂无可配置参数": ": No configuration parameters yet",
	"thinking.off": "Off",
	"保存修改？": "Save changes?",
	丢弃修改: "Discard changes",
	"未能保存，请检查修改后重试。": "Could not save. Check your changes and try again.",
	自动恢复阈值: "Automatic resume threshold",
	子代理指南: "Sub-agent guide",
	代理地址: "Proxy address",
	直连地址: "Direct connection addresses",
	"CA 证书": "CA certificate",
	"请填写必填项并检查输入格式。": "Complete the required fields and check the input format.",
	"配置已保存，但未能完成同步：{0}": "Settings were saved, but synchronization failed: {0}",
	继续运行: "Resume",
	重试启动: "Retry startup",
	"新插件系统（预览）": "New plugin system (preview)",
	"与当前插件页互不影响。这里只验证清单、启停和卸载。": "Independent from the current plugin page. This preview only verifies the manifest, enablement and uninstall.",
	"还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "No plugins yet. Drop a plugin.json with only name and version into a plugin root and it will appear.",
	禁用: "Disable",
	没有声明能力: "No capabilities declared",
	"声明错误：{0}": "Declaration error: {0}",
	"加载错误 {0}": "Load errors {0}",
	"卸载 {0}？data 目录会保留。": "Uninstall {0}? The data directory is kept.",
	"已卸载 {0}，data 目录保留。": "Uninstalled {0}; the data directory was kept.",
	会修改数据: "Changes data",
	"sha256（可选）": "sha256 (optional)",
	"{0} 条匹配": "{0} matches",
	"内核（不可替换）": "kernel (not replaceable)",
	"加载配置中…": "Loading settings…",
	压缩包: "Archive",
	可替换模块: "replaceable module",
	"字段 {0} 需要合法的 JSON。": "Field {0} requires valid JSON.",
	"已保存 {0} 的配置。": "Saved settings for {0}.",
	"当前环境没有桌面窗口，插件窗口只能在桌面端打开。": "No desktop window in this environment; plugin windows open on the desktop app only.",
	"打开窗口 {0}": "Open window {0}",
	收起配置: "Collapse settings",
	"更新（同名替换，data 保留）": "Update (replaces same name, keeps data)",
	"查行为表：模块名或片段（如 prompt、plugin_system.host）": "Search behavior table: module name or fragment (e.g. prompt, plugin_system.host)",
	查询: "Search",
	没有声明依赖: "No declared dependencies",
	"清单、启停、安装、更新与卸载都在这里。": "Manifests, enable/disable, install, update and uninstall all live here.",
	"确定执行 {0}？": "Run {0}?",
	"确定执行 {0}？该操作会修改数据。": "Run {0}? This action modifies data.",
	"自定义配置面板加载失败：{0}": "Failed to load the custom settings panel: {0}",
	"这个插件没有可配置项。": "This plugin has no settings.",
	筛选文档: "Filter documents",
	"Wiki 目录": "Wiki contents",
	目录: "Contents",
	文档导航: "Document navigation",
	没有匹配的文档: "No matching documents",
	没有可用的文档: "No documents available",
	"data 目录会保留": "the data directory is kept",
	"{0} / {1}": "{0} / {1}",
	"{0} 个已启用": "{0} enabled",
	"{0} 个插件": "{0} plugins",
	"{0} 个需要处理": "{0} need attention",
	"依赖：{0}": "Dependencies: {0}",
	入口: "Entry points",
	全局: "Global",
	"分屏打开 {0}": "Open {0} in split view",
	"卸载 {0}": "Uninstall {0}",
	"卸载插件？": "Uninstall plugin?",
	启动失败: "Start failed",
	"启用 {0}": "Enable {0}",
	"在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。": "Add a plugin.json with only name and version to the plugin root and it will appear here.",
	声明错误: "Declaration error",
	复制安装路径: "Copy install path",
	安全模式已跳过: "Skipped in safe mode",
	安装或更新插件: "Install or update a plugin",
	安装来源: "Install source",
	安装来源地址: "Install source address",
	已停止: "Stopped",
	"已安装 {0}": "Installed {0}",
	"已更新 {0}": "Updated {0}",
	"换个关键词，或清除筛选条件。": "Try another keyword, or clear the filters.",
	"插件代码已更新，重启应用后模块覆盖和全局脚本将生效。": "Plugin code was updated. Restart the app to apply module overrides and global scripts.",
	插件配置: "Plugin configuration",
	"搜索插件、能力或路径": "Search plugins, capabilities or paths",
	收起安装: "Close installer",
	"更新会覆盖同名插件，data 目录会保留。": "Updating replaces a plugin with the same name and keeps its data directory.",
	未声明能力: "No capabilities declared",
	"本地目录、压缩包或链接，三种来源共用一条流程。": "Local folder, archive or link: all three share one flow.",
	查询行为表: "Search behavior table",
	"模块名或片段（如 prompt、plugin_system.host）": "Module name or fragment (e.g. prompt, plugin_system.host)",
	正在切换: "Switching",
	正在启动: "Starting",
	"没有加载错误。": "No load errors.",
	没有匹配的插件: "No matching plugins",
	没有描述: "No description",
	清除筛选: "Clear filters",
	"禁用 {0}": "Disable {0}",
	等待启动: "Waiting to start",
	筛选插件: "Filter plugins",
	缺失: "missing",
	行为表查询与加载错误: "Behavior table search and load errors",
	诊断与行为表: "Diagnostics and behavior table",
	运行就绪: "Ready",
	还没有插件: "No plugins yet",
	需要处理: "Need attention",
	"（缺 {0}，可用 pip 安装；不阻止安装）": " (missing {0}; install with pip; installation is not blocked)",
	自定义配置面板加载失败: "Failed to load the custom configuration panel",
	无法加载插件: "Could not load plugins",
	"检查后台连接后再试一次。": "Check the backend connection and try again.",
	再试一次: "Try again",
	"QQ robot": "QQ robot",
	插件页面: "Plugins view",
	源代码与许可证: "Source and licenses",
	"当前显示缓存目录；安装时会重新核对 GitHub 最新发布。": "Showing the cached catalog. Installation checks the latest GitHub release again.",
	插件市场: "Plugin market",
	"从 GitHub 安装插件": "Install plugins from GitHub",
	插件能力: "Capabilities",
	"暂时无法获取市场目录，请检查网络后重试。": "The catalog is unavailable. Check your connection and retry.",
	"正在连接插件市场…": "Connecting to the plugin market…",
	版本暂不可用: "Version unavailable",
	"独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。": "Independently released, installed on demand. Network Exploration optimizes downloads when available; packages are verified before installation.",
	视频与字幕检索: "Video and transcript search",
	内容与信息: "Content and information",
	重新连接: "Reconnect",
	每日内容简报: "Daily content digests",
	消息与协作: "Messaging",
	刷B站: "Bilibili",
	"QQ 私聊与群聊": "QQ chats and groups",
	已安装: "Installed",
	"下载并校验中…": "Downloading and verifying…",
	持久会话: "Persistent sessions",
	消息提醒: "Message reminders",
	暂不可用: "Unavailable",
	changed: "changed",
	有新版本: "Update available",
	审批与文件投递: "Approvals and file delivery",
	"插件已安装，可在“已安装”中配置和管理。": "Plugin installed. Configure and manage it under Installed.",
	"把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。": "Connect Sunday to QQ chats and groups with persistent sessions, approval continuation, and file delivery.",
	"读取视频字幕、整理值得看的内容，生成日报并发送提醒。": "Read video transcripts, curate content, generate daily digests, and send reminders.",
	"Assistant 显示": "Assistant display",
	"只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。": "Display only: whether replies use bubbles, whether they split automatically, and the shown name and avatar. Conversation history, context and the message protocol stay unchanged.",
	"Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。": "Choose whether Assistant replies use message bubbles. When on, replies appear as bubbles; when off they stay as borderless text.",
	使用消息气泡: "Use message bubbles",
	"自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。": "Automatic splitting breaks a long reply into several bubbles at paragraphs and headings. Code blocks, formulas and tables stay intact; when off the whole reply shows as one bubble.",
	自动气泡拆分: "Automatic bubble splitting",
	"显示名称：留空时使用默认名称（Assistant）。": "Display name: leave empty to use the default name (Assistant).",
	"例如 Sunday": "For example, Sunday",
	"头像：上传一张图片并调整裁切；留空时显示名称首字母。": "Avatar: upload an image and adjust the crop. Leave empty to show the first letter of the name.",
	头像: "Avatar",
	"例如 https://example.com/avatar.png": "For example https://example.com/avatar.png",
	图层: "Layers",
	元素: "Elements",
	未分层: "No layer",
	"在「{0}」内": "inside {0}",
	父层自动: "parent layer auto",
	"父层 z={0}": "parent z={0}",
	"自动层（按文档顺序，后绘制的在上）": "Auto sublayer inside the parent layer (document order; later painted on top)",
	关闭编辑器: "Close editor",
	收起面板: "Collapse panels",
	展开面板: "Expand panels",
	编辑模式: "Edit mode",
	"编辑模式已关闭，界面可正常操作。": "Edit mode is off; the interface behaves normally.",
	不保存修改并退出: "Discard changes and exit",
	"在界面上点选组件，或从下面选择。": "Click a component on the page, or pick one below.",
	"正在预览真实界面，修改会立即生效。": "Previewing the real interface; changes apply immediately.",
	属性: "Properties",
	"先选择一个组件。": "Select a component first.",
	"这个组件是业务入口，只能调整外观，不能移动或隐藏。": "This component is a workflow entry point; only appearance can change, not position or visibility.",
	文字颜色: "Text color",
	背景颜色: "Background color",
	"自动（跟随页面）": "Auto (follows the page)",
	锚点: "Anchors",
	横向: "Horizontal",
	纵向: "Vertical",
	不锚定: "Not anchored",
	横向锚点: "Horizontal anchor",
	纵向锚点: "Vertical anchor",
	横向距离: "Horizontal distance",
	纵向距离: "Vertical distance",
	"锚点=到父容器某条边的距离，不会小于 0。": "Anchors are distances to a parent edge and never go below 0.",
	自定义颜色: "Custom color",
	透明: "Transparent",
	主区域底色: "Main surface",
	主区域柔和底色: "Main soft surface",
	应用底色: "App backdrop",
	输入区底色: "Composer surface",
	控件底色: "Control surface",
	背景颜色令牌无效: "Invalid background color token",
	圆角: "Corner radius",
	间距: "Spacing",
	字号: "Font size",
	层级: "Layer order",
	"显示/隐藏图层": "Show or hide layer",
	"锁定/解锁图层": "Lock or unlock layer",
	"第 {0} 层": "Layer {0}",
	显示: "Visible",
	清除这个组件的修改: "Clear this component’s overrides",
	有未发布修改: "Unpublished changes",
	已同步: "Synced",
	发布: "Publish",
	受保护: "Protected",
	仅外观: "Appearance only",
	可编辑: "Editable",
	"文件不是有效的主题 JSON": "The file is not a valid theme JSON.",
	编辑布局: "Edit layout",
	打开编辑器: "Open editor",
	"进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。": "Open the visual editor to adjust colors, backgrounds, corners, font size and layer order. Changes preview immediately and save when published.",
	基础样式: "Base styles",
	窄于: "Narrower than",
	按当前宽度加断点: "Add breakpoint at current width",
	删除这个断点: "Delete this breakpoint",
	"正在编辑窄屏覆盖，只影响该宽度以下。": "Editing a narrow override; it only applies below this width.",
	"正在编辑这一条，只影响它自己。": "Editing this one item only; it does not affect the rest.",
	横向位置: "Horizontal position",
	纵向位置: "Vertical position",
	背景素材: "Background image",
	选择图片: "Choose image",
	更换图片: "Replace image",
	图片位置: "Image position",
	图片缩放: "Image scale",
	拖动九宫格选择图片显示的部分: "Drag the grid to choose which part of the image shows",
	"九宫格就是实际显示的部分，拖动可直接改取景。": "The grid is the visible area; drag it to re-frame the image.",
	模板样式: "Style template",
	允许溢出组件: "Allow overflow",
	"图片过大，单张不能超过 1.5MB": "Image is too large; each file must be under 1.5MB",
	图片读取失败: "Failed to read the image",
	对齐与分布: "Align and distribute",
	右对齐: "Align right",
	垂直居中: "Center vertically",
	底对齐: "Align bottom",
	水平分布: "Distribute horizontally",
	垂直分布: "Distribute vertically",
	top: "Top",
	right: "Right",
	bottom: "Bottom",
	left: "Left",
	上: "Top",
	右: "Right",
	下: "Bottom",
	左: "Left",
	颜色样式: "Color style",
	纯色: "Solid",
	渐变: "Gradient",
	玻璃: "Glass",
	高透: "High transparency",
	低透: "Low transparency",
	高透玻璃: "High-transparency glass",
	低透玻璃: "Low-transparency glass",
	玻璃样式: "Glass style",
	"整个区域换成现成玻璃材质，不再单独调色。": "Replaces the whole area with our glass material; no separate tint editing.",
	适应方式: "Fit",
	铺满: "Cover",
	完整显示: "Contain",
	平铺: "Tile",
	拉伸: "Stretch",
	"支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。": "Supports PNG, JPEG, GIF, WebP, AVIF and SVG; animated images keep playing.",
	实验性功能: "Experimental features",
	实验性: "Experimental",
	"分屏文件预览（实验性）": "Split file preview (experimental)",
	"图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。": "Images, audio, video, PDF, Office and Markdown files open directly in a built-in split pane. The feature is still being refined; turn it off to use the default app when something does not render correctly.",
	玻璃材质: "Glass material",
	"开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。": "Turns the whole area into a glass surface; the color, gradient or image above provides its tint.",
	底色: "Base color",
	上传图片: "Upload image",
	缩放: "Zoom",
	请选择图片文件: "Please choose an image file",
	"图片不能超过 12 MB": "The image must be 12 MB or smaller",
	"图片读取失败，请换一张再试": "Could not read the image. Please try another one.",
	"这张图片打不开，请换一张再试": "This image cannot be opened. Please try another one.",
	"无法处理这张图片，请换一张再试": "This image cannot be processed. Please try another one.",
	拖动图片调整裁切位置: "Drag the image to adjust the crop",
	"拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。": "Drag the image to adjust its position and use the slider to zoom. The area inside the circle is what the avatar shows.",
	头像大小: "Avatar size",
	圆角率: "Corner roundness",
	分组名称: "Group name",
	"删除分组 {0}": "Delete group {0}",
	"删除分组？": "Delete group?",
	所属分组: "Group",
	按分组筛选: "Filter by group",
	新建分组: "New group",
	核心: "Core",
	移动到分组: "Move to group",
	管理分组: "Manage groups",
	"还没有分组。新建一个，把技能归类到瀑布流的各个分区。": "No groups yet. Create one to organize skills into sections of the wall.",
	"这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。": "No skills in this group yet. Use the group menu on a card to move skills here.",
	重命名分组: "Rename group",
	按事件筛选: "Filter by event",
	"这个事件下没有 Hook。切回「全部」看看其他事件。": "No hooks for this event. Switch to \"All\" to see the rest.",
	"会话「{0}」已完成，点击打开": "Session \"{0}\" completed — click to open",
	"会话「{0}」执行失败，点击打开": "Session \"{0}\" failed — click to open",
	打开会话: "Open session",
	桌宠: "Desktop Pet",
	"展开其余 {0} 项": "Show {0} more",
	部分文件不存在: "Some files are missing",
	"调用 {0} 次": "Called {0} times",
	尚未调用: "Not used yet",
	"总调用 {0} 次": "{0} calls in total"
}, yu = /* @__PURE__ */ I("zh-CN"), bu = {
	"zh-CN": hu,
	"zh-TW": gu,
	ja: _u,
	en: vu
};
function xu(e, t = {}) {
	return (bu[yu.value][e] ?? bu["zh-CN"][e] ?? e).replace(/\{(\w+)\}/g, (e, n) => Object.hasOwn(t, n) ? String(t[n]) : e);
}
//#endregion
//#region src/components/UiSelect.vue?vue&type=script&setup=true&lang.ts
var Su = [
	"disabled",
	"aria-label",
	"aria-expanded"
], Cu = {
	key: 0,
	class: "ui-select-arrow"
}, wu = {
	key: 0,
	class: "ui-select-group-label"
}, Tu = ["disabled", "onClick"], Eu = 8, Du = 6, Ou = 96, ku = /*#__PURE__*/ ((e, t) => {
	let n = e.__vccOpts || e;
	for (let [e, r] of t) n[e] = r;
	return n;
})(/* @__PURE__ */ _r({
	name: "UiSelect",
	__name: "UiSelect",
	props: {
		modelValue: {},
		options: {},
		placeholder: {},
		ariaLabel: {},
		direction: {},
		menuAlign: {},
		menuMinWidth: { default: 280 },
		menuWidth: {},
		menuMaxHeight: { default: 320 },
		hideArrow: { type: Boolean },
		disabled: { type: Boolean }
	},
	emits: ["update:modelValue"],
	setup(e, { emit: t }) {
		let n = e, r = t, i = /* @__PURE__ */ I(!1), a = /* @__PURE__ */ I(null), o = /* @__PURE__ */ I(null), s = /* @__PURE__ */ I(null), c = /* @__PURE__ */ I({
			up: !1,
			alignRight: !1,
			left: 0,
			top: 0,
			bottom: null,
			width: 280,
			maxHeight: 320
		}), l = /* @__PURE__ */ I(0), u = /* @__PURE__ */ I(!1), d = /* @__PURE__ */ I({}), f = [
			"--settings-control-solid",
			"--settings-control-text",
			"--ui-select-layer"
		];
		function p() {
			let e = o.value;
			if (!e || typeof getComputedStyle != "function") return {};
			let t = getComputedStyle(e), n = {};
			for (let e of f) {
				let r = t.getPropertyValue(e).trim();
				r && (n[e] = r);
			}
			return n;
		}
		function m() {
			let e = s.value?.offsetHeight ?? 0;
			return e > 0 ? e : n.menuMaxHeight;
		}
		function h(e) {
			let t = o.value?.getBoundingClientRect(), r = window.innerWidth, i = window.innerHeight, a = t ?? {
				left: 0,
				right: 0,
				top: 0,
				bottom: 0,
				width: 0
			}, s = Math.max(120, r - Eu * 2), c = Math.min(n.menuWidth ?? Math.max(n.menuMinWidth, a.width), s), l = i - a.bottom - Du - Eu, u = a.top - Du - Eu, d = n.direction === "up";
			if (!(d ? u >= e : l >= e)) {
				let e = u > l;
				(d ? !e : e) && (d = !d);
			}
			let f = Math.max(Ou, Math.min(n.menuMaxHeight, d ? u : l)), p = n.menuAlign === "right" || !n.menuAlign && a.left + c > r - Eu, m = p ? a.right - c : a.left;
			return {
				up: d,
				alignRight: p,
				left: Math.min(Math.max(Eu, m), Math.max(Eu, r - Eu - c)),
				top: d ? null : a.bottom + Du,
				bottom: d ? i - a.top + Du : null,
				width: c,
				maxHeight: f
			};
		}
		let g = Z(() => {
			let e = c.value;
			return {
				left: `${e.left}px`,
				top: e.top === null ? "auto" : `${e.top}px`,
				bottom: e.bottom === null ? "auto" : `${e.bottom}px`,
				width: `${e.width}px`,
				maxHeight: `${e.maxHeight}px`,
				visibility: u.value ? "visible" : "hidden",
				...d.value
			};
		});
		function _() {
			i.value && (c.value = h(l.value));
		}
		function v() {
			window.addEventListener("resize", _), document.addEventListener("scroll", _, !0);
		}
		function y() {
			window.removeEventListener("resize", _), document.removeEventListener("scroll", _, !0);
		}
		async function b() {
			d.value = p(), l.value = n.menuMaxHeight, u.value = !1, c.value = h(n.menuMaxHeight), i.value = !0, v(), await bn(), i.value && (l.value = m(), c.value = h(l.value), u.value = !0, await bn(), i.value && T()[0]?.focus());
		}
		function x() {
			i.value = !1, u.value = !1, y();
		}
		Rn(() => n.disabled, (e) => {
			e && i.value && x();
		}, { flush: "sync" }), Rn(() => n.options, () => {
			if (!i.value) return;
			let e = document.activeElement instanceof HTMLButtonElement && s.value?.contains(document.activeElement) ? document.activeElement : null;
			bn(() => {
				i.value && (l.value = m(), c.value = h(l.value), e && (!e.isConnected || e.disabled) && (document.activeElement === e || document.activeElement === document.body) && (T()[0] || o.value)?.focus());
			});
		}, { deep: !0 });
		let S = Z(() => {
			let e = n.options.find((e) => e.value === n.modelValue);
			return e?.selectedLabel || e?.label?.replace(/^\s*-\s*/, "") || n.placeholder || xu("未指定");
		}), C = Z(() => ({
			open: i.value,
			"ui-select--up": c.value.up,
			"ui-select--right": n.menuAlign === "right" || !n.menuAlign && c.value.alignRight
		})), w = Z(() => {
			let e = [], t = /* @__PURE__ */ new Map();
			for (let r of n.options) {
				let n = r.group || "", i = t.get(n);
				i === void 0 && (i = e.length, t.set(n, i), e.push({
					group: n,
					options: []
				})), e[i].options.push(r);
			}
			return e;
		});
		function ee() {
			n.disabled || (i.value ? x() : b());
		}
		function T() {
			return Array.from(s.value?.querySelectorAll(".ui-select-option:not(:disabled)") ?? []);
		}
		function te(e) {
			if (e.key === "Tab") {
				o.value?.focus(), x();
				return;
			}
			if (e.key === "Escape") {
				e.preventDefault(), e.stopPropagation(), x(), o.value?.focus();
				return;
			}
			let t = T();
			if (!t.length) return;
			let n = t.indexOf(document.activeElement), r;
			if (e.key === "ArrowDown") r = (n + 1) % t.length;
			else if (e.key === "ArrowUp") r = (n <= 0 ? t.length : n) - 1;
			else if (e.key === "Home") r = 0;
			else if (e.key === "End") r = t.length - 1;
			else return;
			e.preventDefault(), t[r]?.focus();
		}
		function ne(e) {
			n.disabled || e.disabled || (r("update:modelValue", e.value), x(), o.value?.focus());
		}
		function E(e) {
			let t = e.target;
			t && (a.value?.contains(t) || s.value?.contains(t) || x());
		}
		return Nr(() => {
			document.addEventListener("pointerdown", E);
		}), Lr(() => {
			document.removeEventListener("pointerdown", E), y();
		}), (t, n) => (U(), W("div", {
			ref_key: "root",
			ref: a,
			class: k(["ui-select", C.value])
		}, [K("button", {
			ref_key: "triggerEl",
			ref: o,
			class: "ui-select-trigger",
			type: "button",
			disabled: e.disabled,
			"aria-label": e.ariaLabel || L(xu)("当前选择：{0}", { 0: S.value }),
			"aria-expanded": i.value,
			onClick: ee,
			onKeydown: [n[0] ||= Ss((e) => i.value && te(e), ["esc"]), n[1] ||= Ss((e) => i.value && x(), ["tab"])]
		}, [K("span", null, A(S.value), 1), e.hideArrow ? Y("", !0) : (U(), W("span", Cu))], 40, Su), (U(), G($n, { to: "body" }, [i.value ? (U(), W("div", {
			key: 0,
			ref_key: "menuEl",
			ref: s,
			class: k(["ui-select-menu", { "ui-select-menu--up": c.value.up }]),
			style: pe(g.value),
			onKeydown: te
		}, [(U(!0), W(V, null, B(w.value, (t) => (U(), W("div", {
			key: t.group || "default",
			class: "ui-select-group"
		}, [t.group ? (U(), W("div", wu, A(t.group), 1)) : Y("", !0), (U(!0), W(V, null, B(t.options, (t) => (U(), W("button", {
			key: t.value,
			class: k(["ui-select-option", {
				active: t.selected ?? t.value === e.modelValue,
				"active-accent": t.activeAccent,
				"separator-before": t.separatorBefore,
				disabled: t.disabled
			}]),
			type: "button",
			disabled: t.disabled,
			onClick: (e) => ne(t)
		}, A(t.label), 11, Tu))), 128))]))), 128))], 38)) : Y("", !0)]))], 2));
	}
}), [["__scopeId", "data-v-1745baef"]]), Au = { class: "nx-view-stack" }, ju = { class: "nx-download-stats" }, Mu = { class: "nx-panel-heading" }, Nu = { class: "nx-inline-form" }, Pu = ["disabled"], Fu = { class: "nx-download-options" }, Iu = { class: "nx-download-option" }, Lu = { class: "nx-download-option" }, Ru = ["aria-expanded"], zu = {
	key: 0,
	class: "nx-form-grid"
}, Bu = { class: "nx-form-field" }, Vu = { class: "nx-list-toolbar" }, Hu = { class: "nx-filter-tabs" }, Uu = { class: "nx-panel nx-task-list" }, Wu = ["data-task"], Gu = { class: "nx-file-icon" }, Ku = { class: "nx-download-body" }, qu = { class: "nx-task-title" }, Ju = ["aria-valuenow", "aria-label"], Yu = { class: "nx-task-meta" }, Xu = { key: 0 }, Zu = { key: 1 }, Qu = { key: 2 }, $u = { class: "nx-task-controls" }, ed = ["disabled", "onClick"], td = ["disabled", "onClick"], nd = [
	"aria-label",
	"aria-expanded",
	"onClick"
], rd = {
	key: 0,
	class: "nx-task-details"
}, id = { class: "nx-subtle" }, ad = { class: "nx-actions" }, od = { class: "nx-small-select" }, sd = ["disabled", "onClick"], cd = ["disabled", "onClick"], ld = ["disabled", "onClick"], ud = {
	key: 0,
	class: "nx-empty"
}, dd = {
	__name: "TransferView",
	props: { session: Object },
	setup(t) {
		let n = t, r = /* @__PURE__ */ I("active"), i = /* @__PURE__ */ I(""), a = /* @__PURE__ */ I(""), o = /* @__PURE__ */ I(""), s = /* @__PURE__ */ I(""), c = /* @__PURE__ */ I("auto"), l = /* @__PURE__ */ I(!1), u = /* @__PURE__ */ I(8), d = /* @__PURE__ */ I(0), f = /* @__PURE__ */ I(!1), p = /* @__PURE__ */ I(""), m = [
			1,
			2,
			4,
			8,
			16
		].map((e) => ({
			value: String(e),
			label: String(e)
		})), h = [
			{
				value: "0",
				label: "不限速"
			},
			{
				value: "1048576",
				label: "1 MB/s"
			},
			{
				value: "5242880",
				label: "5 MB/s"
			},
			{
				value: "10485760",
				label: "10 MB/s"
			}
		], g = Z(() => [
			{
				value: "auto",
				label: "自动（跟随加速）"
			},
			{
				value: "direct",
				label: "直接连接"
			},
			{
				value: "proxy",
				label: "当前代理",
				disabled: !n.session.state?.proxy?.running
			}
		]), _ = /* @__PURE__ */ It({}), v = Z(() => n.session.tasks.reduce((e, t) => e + (Number(t.downloadSpeed) || 0), 0)), y = Z(() => n.session.tasks.map((e) => ({
			...n.session.state?.downloads?.find((t) => t.gid === e.gid),
			...e
		})).filter((e) => r.value === "all" || (r.value === "complete" ? e.status === "complete" : !["complete", "removed"].includes(e.status)))), b = Z(() => n.session.tasks.filter((e) => !["complete", "removed"].includes(e.status)).length), x = Z(() => n.session.tasks.filter((e) => e.status === "complete").length);
		function S(e) {
			return Math.min(100, Number(e.completedLength || 0) / Math.max(1, Number(e.totalLength || 0)) * 100);
		}
		function C(e) {
			let t = (Number(e.totalLength || 0) - Number(e.completedLength || 0)) / Math.max(0, Number(e.downloadSpeed || 0));
			return Number.isFinite(t) && t > 0 ? t < 60 ? `约 ${Math.ceil(t)} 秒` : `约 ${Math.ceil(t / 60)} 分钟` : "等待传输";
		}
		async function w() {
			let e = a.value.trim(), t = {
				url: i.value.trim(),
				...e ? { filename: e } : {},
				connections: Number(u.value),
				route: c.value,
				sha256: s.value.trim(),
				...Number(d.value) > 0 ? { bytes_per_second: Number(d.value) } : {},
				...o.value.trim() ? { directory: o.value.trim() } : {}
			};
			await n.session.run("transfer.add", t, "已开始下载") && (i.value = "", a.value = "", s.value = "", await n.session.loadTasks());
		}
		function ee(e) {
			f.value = !1;
			let t = (e.dataTransfer?.getData("text/uri-list") || e.dataTransfer?.getData("text/plain") || "").split(/\r?\n/).map((e) => e.trim()).find(Boolean);
			if (!t || !/^https?:\/\//i.test(t)) {
				n.session.error = "请拖入一个 HTTP 或 HTTPS 下载链接";
				return;
			}
			i.value = t, n.session.notice = "链接已填入，点“开始下载”";
		}
		async function T(e, t) {
			e.status === "recoverable" && t === "resume" && !await n.session.run("transfer.recover", {}) || (await n.session.run("transfer.action", {
				gid: e.gid,
				action: t
			}), await n.session.loadTasks());
		}
		async function te(e, t) {
			t !== (_[e.gid] || "0") && (_[e.gid] = t, await n.session.run("transfer.action", {
				gid: e.gid,
				action: "limit",
				bytes_per_second: Number(t)
			}, "下载限速已更新"));
		}
		async function ne(e) {
			let t = await n.session.run("transfer.verify", { gid: e.gid });
			t && (t.verified === !1 ? n.session.error = "文件与预期校验值不一致，请核对下载来源" : n.session.notice = t.verified === !0 ? "文件校验通过" : `文件校验值：${t.sha256}`);
		}
		return (n, E) => (U(), W("div", Au, [
			E[35] ||= K("div", { class: "nx-section-heading" }, [K("div", null, [K("h2", null, "下载"), K("p", null, "粘贴链接或把链接拖进来，点“开始下载”。")])], -1),
			K("div", ju, [
				K("div", null, [E[15] ||= K("span", null, "进行中", -1), K("strong", null, A(b.value), 1)]),
				K("div", null, [E[16] ||= K("span", null, "已完成", -1), K("strong", null, A(x.value), 1)]),
				K("div", null, [E[17] ||= K("span", null, "总速度", -1), K("strong", null, A(L(bc)(v.value)), 1)])
			]),
			K("form", {
				class: k(["nx-panel nx-download-composer", { "is-dragging": f.value }]),
				"data-download-drop": "",
				onSubmit: bs(w, ["prevent"]),
				onDragover: E[8] ||= bs(() => {}, ["prevent"]),
				onDragenter: E[9] ||= bs((e) => f.value = !0, ["prevent"]),
				onDragleave: E[10] ||= (e) => f.value = !1,
				onDrop: bs(ee, ["prevent"])
			}, [
				K("div", Mu, [K("h2", null, [q(L(Ys), { size: 17 }), E[18] ||= J("新建下载", -1)]), E[19] ||= K("span", { class: "nx-subtle" }, "支持 HTTP / HTTPS", -1)]),
				K("div", Nu, [z(K("input", {
					"onUpdate:modelValue": E[0] ||= (e) => i.value = e,
					name: "url",
					class: "nx-input",
					required: "",
					placeholder: "粘贴下载链接，或把链接拖到这里",
					"aria-label": "下载链接"
				}, null, 512), [[Q, i.value]]), K("button", {
					class: "btn nx-button btn--primary",
					disabled: !!t.session.busy || !i.value.trim()
				}, " 开始下载 ", 8, Pu)]),
				K("div", Fu, [K("div", Iu, [E[20] ||= K("span", null, "并行数量", -1), q(ku, {
					"model-value": String(u.value),
					options: L(m),
					"aria-label": "并行数量",
					"data-transfer-connections": "",
					"menu-min-width": 100,
					"onUpdate:modelValue": E[1] ||= (e) => u.value = Number(e)
				}, null, 8, ["model-value", "options"])]), K("div", Lu, [E[21] ||= K("span", null, "下载限速", -1), q(ku, {
					"model-value": String(d.value),
					options: h,
					"aria-label": "下载限速",
					"data-transfer-speed": "",
					"menu-min-width": 120,
					"onUpdate:modelValue": E[2] ||= (e) => d.value = Number(e)
				}, null, 8, ["model-value"])])]),
				K("button", {
					type: "button",
					class: "btn nx-button btn--quiet nx-options-button",
					"aria-expanded": l.value,
					onClick: E[3] ||= (e) => l.value = !l.value
				}, [E[22] ||= J(" 更多选项", -1), q(L(Ws), { size: 13 })], 8, Ru),
				l.value ? (U(), W("div", zu, [
					K("label", null, [E[23] ||= K("span", null, "文件名", -1), z(K("input", {
						"onUpdate:modelValue": E[4] ||= (e) => a.value = e,
						class: "nx-input",
						placeholder: "自动使用链接中的文件名"
					}, null, 512), [[Q, a.value]])]),
					K("label", null, [E[24] ||= K("span", null, "保存目录", -1), z(K("input", {
						"onUpdate:modelValue": E[5] ||= (e) => o.value = e,
						class: "nx-input",
						placeholder: "留空使用默认下载目录"
					}, null, 512), [[Q, o.value]])]),
					K("label", null, [E[25] ||= K("span", null, "文件校验值（可选）", -1), z(K("input", {
						"onUpdate:modelValue": E[6] ||= (e) => s.value = e,
						class: "nx-input",
						placeholder: "SHA-256"
					}, null, 512), [[Q, s.value]])]),
					K("div", Bu, [E[26] ||= K("span", null, "下载线路", -1), q(ku, {
						modelValue: c.value,
						"onUpdate:modelValue": E[7] ||= (e) => c.value = e,
						options: g.value,
						"aria-label": "下载线路",
						"data-transfer-route": "",
						"menu-min-width": 180
					}, null, 8, ["modelValue", "options"])])
				])) : Y("", !0)
			], 34),
			K("div", Vu, [K("div", Hu, [
				K("button", {
					class: k({ active: r.value === "active" }),
					onClick: E[11] ||= (e) => r.value = "active"
				}, [E[27] ||= J(" 进行中", -1), K("span", null, A(b.value), 1)], 2),
				K("button", {
					class: k({ active: r.value === "complete" }),
					onClick: E[12] ||= (e) => r.value = "complete"
				}, [E[28] ||= J(" 已完成", -1), K("span", null, A(x.value), 1)], 2),
				K("button", {
					class: k({ active: r.value === "all" }),
					onClick: E[13] ||= (e) => r.value = "all"
				}, " 全部 ", 2)
			]), K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				"aria-label": "刷新下载列表",
				onClick: E[14] ||= (e) => t.session.loadTasks()
			}, [q(L(dc), { size: 15 })])]),
			K("section", Uu, [(U(!0), W(V, null, B(y.value, (n) => (U(), W("article", {
				key: n.gid,
				class: "nx-download-row",
				"data-task": n.gid
			}, [
				K("div", Gu, [q(L(Qs), {
					size: 22,
					"stroke-width": 1.5
				})]),
				K("div", Ku, [
					K("div", qu, [K("strong", null, A(n.filename || "未命名下载"), 1), K("span", { class: k({ "nx-state-error": n.status === "error" }) }, A(L(xc)(n.status)), 3)]),
					K("div", {
						class: "nx-progress-track",
						role: "progressbar",
						"aria-valuenow": Math.round(S(n)),
						"aria-valuemin": "0",
						"aria-valuemax": "100",
						"aria-label": `${n.filename || "下载"}的进度`
					}, [K("span", { style: pe({ width: `${S(n)}%` }) }, null, 4)], 8, Ju),
					K("div", Yu, [K("span", null, [
						J(A(L(e)(n.completedLength)), 1),
						E[29] ||= K("span", { class: "nx-meta-divider" }, " / ", -1),
						J(A(L(e)(n.totalLength)), 1)
					]), n.status === "active" ? (U(), W("span", Xu, [
						J(A(L(bc)(n.downloadSpeed)), 1),
						E[30] ||= K("span", { class: "nx-meta-divider" }, "·", -1),
						J(A(C(n)), 1)
					])) : n.status === "complete" ? (U(), W("span", Zu, "已保存到本地")) : n.status === "error" ? (U(), W("span", Qu, "链接可能失效，或下载源暂时不可用")) : Y("", !0)])
				]),
				K("div", $u, [n.status === "active" || n.status === "waiting" ? (U(), W("button", {
					key: 0,
					class: "btn nx-button btn--secondary nx-icon-button",
					"aria-label": "暂停下载",
					"data-task-action": "pause",
					disabled: !!t.session.busy,
					onClick: (e) => T(n, "pause")
				}, [q(L(oc), { size: 15 })], 8, ed)) : ["paused", "recoverable"].includes(n.status) ? (U(), W("button", {
					key: 1,
					class: "btn nx-button btn--secondary nx-icon-button",
					"aria-label": "继续下载",
					"data-task-action": "resume",
					disabled: !!t.session.busy,
					onClick: (e) => T(n, "resume")
				}, [q(L(sc), { size: 15 })], 8, td)) : Y("", !0), K("button", {
					class: "btn nx-button btn--quiet nx-icon-button",
					"aria-label": p.value === n.gid ? "收起下载详情" : "展开下载详情",
					"aria-expanded": p.value === n.gid,
					onClick: (e) => p.value = p.value === n.gid ? "" : n.gid
				}, [(U(), G(Wr(p.value === n.gid ? L(Ks) : L(Ws)), { size: 15 }))], 8, nd)]),
				p.value === n.gid ? (U(), W("div", rd, [K("span", id, A(n.directory || "默认下载目录"), 1), K("div", ad, [
					K("div", od, [E[31] ||= K("span", null, "下载速度", -1), q(ku, {
						"model-value": _[n.gid] || "0",
						options: h,
						"aria-label": "下载速度限制",
						"data-transfer-task-limit": "",
						"menu-min-width": 120,
						"onUpdate:modelValue": (e) => te(n, e)
					}, null, 8, ["model-value", "onUpdate:modelValue"])]),
					["complete", "removed"].includes(n.status) ? Y("", !0) : (U(), W("button", {
						key: 0,
						class: "btn nx-button btn--quiet",
						disabled: !!t.session.busy,
						onClick: (e) => T(n, "first")
					}, [q(L(Hs), { size: 13 }), E[32] ||= J("优先下载", -1)], 8, sd)),
					n.status === "complete" ? (U(), W("button", {
						key: 1,
						class: "btn nx-button btn--quiet",
						disabled: !!t.session.busy,
						onClick: (e) => ne(n)
					}, [q(L(mc), { size: 13 }), E[33] ||= J("校验文件", -1)], 8, cd)) : Y("", !0),
					["complete", "removed"].includes(n.status) ? Y("", !0) : (U(), W("button", {
						key: 2,
						class: "btn nx-button btn--quiet nx-danger-text",
						disabled: !!t.session.busy,
						onClick: (e) => T(n, "cancel")
					}, [q(L(vc), { size: 13 }), E[34] ||= J("取消下载 ", -1)], 8, ld))
				])])) : Y("", !0)
			], 8, Wu))), 128)), y.value.length ? Y("", !0) : (U(), W("div", ud, [
				q(L(Ys), {
					size: 32,
					"stroke-width": 1.3
				}),
				K("strong", null, A(r.value === "complete" ? "还没有完成的下载" : "准备好下载了吗？"), 1),
				K("p", null, A(r.value === "complete" ? "完成的文件会显示在这里。" : "把链接放到上面的框里，就会开始下载。"), 1)
			]))])
		]));
	}
}, fd = { class: "nx-view-stack" }, pd = { class: "nx-panel nx-diagnose-start" }, md = { class: "nx-diagnose-symbol" }, hd = { class: "nx-input-with-icon" }, gd = ["disabled"], _d = { class: "nx-diagnose-options" }, vd = {
	key: 0,
	class: "nx-panel nx-diagnose-pending",
	"aria-live": "polite"
}, yd = {
	key: 1,
	class: "nx-panel nx-report"
}, bd = { class: "nx-report-heading" }, xd = { class: "nx-check-list" }, Sd = { key: 0 }, Cd = {
	key: 0,
	class: "nx-report-advice"
}, wd = ["aria-expanded"], Td = {
	key: 1,
	class: "nx-check-evidence"
}, Ed = {
	key: 2,
	class: "nx-history"
}, Dd = { class: "nx-section-heading" }, Od = { class: "nx-subtle" }, kd = ["onClick"], Ad = {
	key: 3,
	class: "nx-empty nx-diagnose-empty"
}, jd = {
	__name: "DiagnoseView",
	props: {
		session: Object,
		report: Object
	},
	setup(e) {
		let t = e, n = /* @__PURE__ */ I("github.com"), r = /* @__PURE__ */ I(null), i = /* @__PURE__ */ I(!1), a = /* @__PURE__ */ I("basic");
		Rn(() => t.report, (e) => {
			e && (r.value = e, n.value = e.target);
		}, { immediate: !0 });
		let o = Z(() => r.value || t.session.state?.reports?.at(-1));
		function s(e) {
			return {
				DNS: "找到网站地址",
				TCP: "建立网络连接",
				"TLS / HTTP": "检查安全连接与响应",
				Ping: "检查响应延迟",
				Traceroute: "检查访问路径",
				ICMP: "检查网络响应"
			}[e] || e;
		}
		async function c() {
			let e = await t.session.diagnose(n.value, a.value);
			e?.report && (r.value = e.report, i.value = !1);
		}
		return (t, l) => (U(), W("div", fd, [
			K("section", pd, [
				K("div", md, [q(L(Ls), {
					size: 25,
					"stroke-width": 1.5
				})]),
				l[8] ||= K("h2", null, "看看哪里没连上", -1),
				l[9] ||= K("p", null, "输入一个网站，检查地址解析、连接和响应。", -1),
				K("form", {
					class: "nx-inline-form",
					"data-diagnose-form": "",
					onSubmit: bs(c, ["prevent"])
				}, [K("label", hd, [q(L(tc), { size: 16 }), z(K("input", {
					"onUpdate:modelValue": l[0] ||= (e) => n.value = e,
					name: "target",
					class: "nx-input",
					placeholder: "例如 github.com",
					required: "",
					"aria-label": "检测网站"
				}, null, 512), [[Q, n.value]])]), K("button", {
					class: "btn nx-button btn--primary",
					disabled: !!e.session.busy
				}, [q(L(fc), { size: 15 }), J(A(e.session.busy === "diagnose" ? "检查中…" : "开始检测"), 1)], 8, gd)], 32),
				K("div", _d, [
					K("label", null, [z(K("input", {
						"onUpdate:modelValue": l[1] ||= (e) => a.value = e,
						type: "radio",
						value: "basic"
					}, null, 512), [[us, a.value]]), l[5] ||= J("快速检查", -1)]),
					K("label", null, [z(K("input", {
						"onUpdate:modelValue": l[2] ||= (e) => a.value = e,
						type: "radio",
						value: "ping"
					}, null, 512), [[us, a.value]]), l[6] ||= J("加测延迟", -1)]),
					K("label", null, [z(K("input", {
						"onUpdate:modelValue": l[3] ||= (e) => a.value = e,
						type: "radio",
						value: "traceroute"
					}, null, 512), [[us, a.value]]), l[7] ||= J("查看访问路径", -1)])
				])
			]),
			e.session.busy === "diagnose" ? (U(), W("section", vd, [
				l[10] ||= K("div", { class: "nx-skeleton nx-skeleton-title" }, null, -1),
				l[11] ||= K("p", null, "正在检查网站地址、连接和安全响应…", -1),
				(U(), W(V, null, B(3, (e) => K("div", {
					key: e,
					class: "nx-skeleton nx-skeleton-row"
				})), 64))
			])) : o.value ? (U(), W("section", yd, [
				K("div", bd, [K("span", { class: k(["nx-result-icon", { "is-failure": o.value.failures > 0 }]) }, [o.value.failures ? (U(), G(L(vc), {
					key: 1,
					size: 22
				})) : (U(), G(L(Us), {
					key: 0,
					size: 22
				}))], 2), K("div", null, [K("h2", null, A(o.value.failures > 0 ? "发现未通过的检查" : "检查通过"), 1), K("p", null, [
					J(A(o.value.target), 1),
					l[12] ||= K("span", { class: "nx-meta-divider" }, "·", -1),
					J(A(L(Sc)(o.value.time)), 1)
				])])]),
				K("div", xd, [(U(!0), W(V, null, B(o.value.checks || [], (e, t) => (U(), W("div", {
					key: t,
					class: "nx-check-row"
				}, [
					K("span", { class: k(["nx-check-status", { "is-failure": !e.ok }]) }, [e.ok ? (U(), G(L(Us), {
						key: 0,
						size: 14
					})) : (U(), G(L(vc), {
						key: 1,
						size: 14
					}))], 2),
					K("strong", null, A(s(e.stage)), 1),
					K("span", null, A(e.ok ? "通过" : "未通过"), 1),
					e.ms == null ? Y("", !0) : (U(), W("time", Sd, A(e.ms) + " ms", 1))
				]))), 128))]),
				o.value.recommendation ? (U(), W("p", Cd, A(o.value.recommendation), 1)) : Y("", !0),
				K("button", {
					class: "btn nx-button btn--quiet nx-report-detail-button",
					"aria-expanded": i.value,
					onClick: l[4] ||= (e) => i.value = !i.value
				}, [J(A(i.value ? "收起" : "查看") + "检查详情", 1), q(L(Ws), { size: 13 })], 8, wd),
				i.value ? (U(), W("div", Td, [(U(!0), W(V, null, B(o.value.checks || [], (e, t) => (U(), W("div", { key: t }, [K("strong", null, A(s(e.stage)), 1), K("p", null, A(e.evidence || e.address || e.addresses?.join("、") || (e.status ? `网站响应：${e.status}` : "未提供额外信息")), 1)]))), 128))])) : Y("", !0)
			])) : Y("", !0),
			e.session.state?.reports?.length ? (U(), W("section", Ed, [K("div", Dd, [l[13] ||= K("h2", null, "最近检查", -1), K("span", Od, A(e.session.state.reports.length) + " 条记录", 1)]), (U(!0), W(V, null, B([...e.session.state.reports].reverse().slice(0, 12), (e) => (U(), W("button", {
				key: e.id,
				class: "nx-history-row",
				onClick: (t) => r.value = e
			}, [
				K("span", { class: k(["nx-history-result", { "is-failure": e.failures > 0 }]) }, [(U(), G(Wr(e.failures ? L(vc) : L(Us)), { size: 14 }))], 2),
				K("strong", null, A(e.target), 1),
				K("span", null, A(e.failures ? "有未通过的检查" : "检查通过"), 1),
				K("time", null, A(L(Sc)(e.time)), 1),
				q(L(Gs), { size: 15 })
			], 8, kd))), 128))])) : o.value ? Y("", !0) : (U(), W("div", Ad, [q(L(qs), { size: 25 }), l[14] ||= K("span", null, "检查记录会保存在这里，方便下次对照。", -1)]))
		]));
	}
}, Md = { class: "nx-view-stack" }, Nd = { class: "nx-section-heading" }, Pd = ["aria-expanded"], Fd = { class: "nx-panel nx-interface-list" }, Id = { class: "nx-control-icon" }, Ld = { key: 0 }, Rd = {
	key: 0,
	class: "nx-empty nx-empty--small"
}, zd = { class: "nx-form-grid" }, Bd = { class: "nx-form-field" }, Vd = ["disabled"], Hd = { class: "nx-panel nx-form" }, Ud = { class: "nx-panel-heading" }, Wd = ["disabled"], Gd = {
	key: 0,
	class: "nx-query-result"
}, Kd = { class: "nx-subtle" }, qd = { key: 0 }, Jd = { class: "nx-settings-fold" }, Yd = ["aria-expanded"], Xd = {
	key: 0,
	class: "nx-panel nx-form"
}, Zd = ["onUpdate:modelValue"], Qd = ["onClick"], $d = { class: "nx-actions" }, ef = ["disabled"], tf = ["disabled"], nf = { key: 0 }, rf = {
	__name: "NetworkSettings",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(!1), r = /* @__PURE__ */ I(""), i = /* @__PURE__ */ I("1.1.1.1,8.8.8.8"), a = /* @__PURE__ */ I("github.com"), o = /* @__PURE__ */ I("system"), s = /* @__PURE__ */ I(null), c = /* @__PURE__ */ I(!1), l = /* @__PURE__ */ I(null), u = /* @__PURE__ */ I(""), d = /* @__PURE__ */ I(null), f = Z(() => t.session.interfaces.map((e) => ({
			value: String(e.index),
			label: e.name
		}))), p = [
			{
				value: "system",
				label: "系统 DNS"
			},
			{
				value: "cloudflare",
				label: "Cloudflare"
			},
			{
				value: "google",
				label: "Google"
			}
		], m = [
			{
				value: "DIRECT",
				label: "直接连接"
			},
			{
				value: "PROXY",
				label: "通过代理"
			},
			{
				value: "REJECT",
				label: "阻止连接"
			}
		];
		async function h() {
			s.value = await t.session.run("dns.query", {
				domain: a.value.trim(),
				provider: o.value,
				type: "A"
			});
		}
		async function g() {
			if (r.value && await t.session.run("system.apply", {
				kind: "dns",
				interface_index: Number(r.value),
				servers: i.value.split(/[,，]/).map((e) => e.trim()).filter(Boolean)
			}, "DNS 设置已更新")) {
				n.value = !1;
				let e = await t.session.read("interfaces");
				e && (t.session.interfaces = e.interfaces || []);
			}
		}
		function _() {
			l.value = (t.session.state.rules || []).map((e) => ({ ...e })), c.value = !c.value;
		}
		async function v() {
			await t.session.run("rules.save", {
				revision: t.session.state.revision,
				rules: l.value
			}, "规则已保存");
		}
		async function y() {
			d.value = await t.session.run("rules.test", { domain: u.value });
		}
		return (t, b) => (U(), W("div", Md, [
			K("div", Nd, [b[8] ||= K("div", null, [K("h2", null, "本机网络"), K("p", null, "查看当前地址和正在使用的 DNS。")], -1), K("button", {
				class: "btn nx-button btn--secondary",
				"aria-expanded": n.value,
				onClick: b[0] ||= (e) => n.value = !n.value
			}, [q(L(pc), { size: 15 }), b[7] ||= J("调整 DNS ", -1)], 8, Pd)]),
			K("section", Fd, [(U(!0), W(V, null, B(e.session.interfaces, (e) => (U(), W("article", {
				key: e.index,
				class: "nx-interface"
			}, [K("span", Id, [q(L(ic), { size: 20 })]), K("div", null, [K("strong", null, A(e.name), 1), K("dl", null, [
				K("div", null, [b[9] ||= K("dt", null, "本机地址", -1), K("dd", null, A(e.ipv4?.join("、") || "没有 IPv4 地址"), 1)]),
				K("div", null, [b[10] ||= K("dt", null, "DNS", -1), K("dd", null, A(e.dns?.join("、") || "由系统提供"), 1)]),
				e.gateway?.length ? (U(), W("div", Ld, [b[11] ||= K("dt", null, "网关", -1), K("dd", null, A(e.gateway.join("、")), 1)])) : Y("", !0)
			])])]))), 128)), e.session.interfaces.length ? Y("", !0) : (U(), W("div", Rd, [q(L(ic), { size: 25 }), b[12] ||= K("span", null, "暂时没有读取到网络接口。", -1)]))]),
			n.value ? (U(), W("form", {
				key: 0,
				class: "nx-panel nx-form",
				onSubmit: bs(g, ["prevent"])
			}, [
				b[15] ||= K("h2", null, "调整 DNS", -1),
				K("div", zd, [K("div", Bd, [b[13] ||= K("span", null, "网络接口", -1), q(ku, {
					modelValue: r.value,
					"onUpdate:modelValue": b[1] ||= (e) => r.value = e,
					options: f.value,
					placeholder: "选择正在使用的网络",
					"aria-label": "网络接口",
					"data-network-interface": "",
					"menu-min-width": 180
				}, null, 8, ["modelValue", "options"])]), K("label", null, [b[14] ||= K("span", null, "DNS 地址", -1), z(K("input", {
					"onUpdate:modelValue": b[2] ||= (e) => i.value = e,
					class: "nx-input",
					required: "",
					placeholder: "多个地址用逗号隔开"
				}, null, 512), [[Q, i.value]])])]),
				b[16] ||= K("p", { class: "nx-help" }, "修改前会保存原设置，之后可在“防护”中恢复。", -1),
				K("button", {
					class: "btn nx-button btn--secondary",
					disabled: !!e.session.busy || !r.value
				}, " 确认并申请修改 ", 8, Vd)
			], 32)) : Y("", !0),
			K("section", Hd, [
				K("div", Ud, [K("h2", null, [q(L(tc), { size: 17 }), b[17] ||= J("查询网站地址", -1)])]),
				K("form", {
					class: "nx-inline-form",
					onSubmit: bs(h, ["prevent"])
				}, [
					z(K("input", {
						"onUpdate:modelValue": b[3] ||= (e) => a.value = e,
						class: "nx-input",
						placeholder: "输入域名",
						"aria-label": "查询域名",
						required: ""
					}, null, 512), [[Q, a.value]]),
					q(ku, {
						modelValue: o.value,
						"onUpdate:modelValue": b[4] ||= (e) => o.value = e,
						class: "nx-shared-select",
						options: p,
						"aria-label": "查询方式",
						"data-network-dns-provider": "",
						"menu-min-width": 150
					}, null, 8, ["modelValue"]),
					K("button", {
						class: "btn nx-button btn--secondary",
						disabled: !!e.session.busy
					}, [q(L(fc), { size: 14 }), b[18] ||= J("查询 ", -1)], 8, Wd)
				], 32),
				s.value ? (U(), W("div", Gd, [
					K("span", Kd, A(s.value.domain) + " · " + A(s.value.ms || 0) + " ms", 1),
					(U(!0), W(V, null, B(s.value.addresses || s.value.answers || [], (e, t) => (U(), W("div", {
						key: t,
						class: "nx-query-address"
					}, A(typeof e == "string" ? e : e.data), 1))), 128)),
					(s.value.addresses || s.value.answers || []).length ? Y("", !0) : (U(), W("span", qd, "没有查到地址"))
				])) : Y("", !0)
			]),
			K("section", Jd, [K("button", {
				class: "btn nx-button btn--quiet",
				"aria-expanded": c.value,
				onClick: _
			}, [b[19] ||= J(" 网站规则匹配预览", -1), q(L(Ws), { size: 13 })], 8, Yd), c.value ? (U(), W("div", Xd, [
				b[21] ||= K("p", { class: "nx-help" }, " 用于检查匹配结果；实际代理分流以订阅中的规则为准。 ", -1),
				(U(!0), W(V, null, B(l.value, (e, t) => (U(), W("div", {
					key: t,
					class: "nx-rule-row"
				}, [
					z(K("input", {
						"onUpdate:modelValue": (t) => e.domain = t,
						class: "nx-input",
						placeholder: "例如 github.com",
						"aria-label": "规则域名"
					}, null, 8, Zd), [[Q, e.domain]]),
					q(ku, {
						modelValue: e.outbound,
						"onUpdate:modelValue": (t) => e.outbound = t,
						class: "nx-rule-select",
						options: m,
						"aria-label": "规则出口",
						"data-network-rule-outbound": "",
						"menu-min-width": 140
					}, null, 8, ["modelValue", "onUpdate:modelValue"]),
					K("button", {
						class: "btn nx-button btn--quiet nx-icon-button",
						"aria-label": "删除规则",
						onClick: (e) => l.value.splice(t, 1)
					}, [q(L(vc), { size: 14 })], 8, Qd)
				]))), 128)),
				K("div", $d, [K("button", {
					class: "btn nx-button btn--quiet",
					onClick: b[5] ||= (e) => l.value.push({
						domain: "",
						outbound: "DIRECT"
					})
				}, [q(L(cc), { size: 14 }), b[20] ||= J("添加规则", -1)]), K("button", {
					class: "btn nx-button btn--secondary",
					disabled: !!e.session.busy,
					onClick: v
				}, " 保存规则 ", 8, ef)]),
				K("form", {
					class: "nx-inline-form",
					onSubmit: bs(y, ["prevent"])
				}, [z(K("input", {
					"onUpdate:modelValue": b[6] ||= (e) => u.value = e,
					class: "nx-input",
					required: "",
					placeholder: "输入域名，看看会匹配到哪里",
					"aria-label": "测试规则域名"
				}, null, 512), [[Q, u.value]]), K("button", {
					class: "btn nx-button btn--secondary",
					disabled: !!e.session.busy
				}, " 测试匹配 ", 8, tf)], 32),
				d.value ? (U(), W("p", nf, A(d.value.matched ? `匹配到 ${d.value.matched.domain}` : "未匹配到专属规则") + " · " + A({
					DIRECT: "直接连接",
					PROXY: "通过代理",
					REJECT: "阻止连接"
				}[d.value.outbound]), 1)) : Y("", !0)
			])) : Y("", !0)])
		]));
	}
}, af = { class: "nx-view-stack" }, of = { class: "nx-section-heading" }, sf = { class: "nx-subtle" }, cf = { class: "nx-input-with-icon" }, lf = ["disabled"], uf = { class: "nx-panel nx-table-panel" }, df = {
	key: 0,
	class: "nx-table-loading"
}, ff = {
	key: 1,
	class: "nx-table-scroll"
}, pf = { class: "nx-table" }, mf = ["title"], hf = { key: 0 }, gf = { class: "nx-data-cell" }, _f = { class: "nx-protocol" }, vf = {
	key: 0,
	class: "nx-empty"
}, yf = {
	__name: "ConnectionsView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(""), r = /* @__PURE__ */ I([]), i = /* @__PURE__ */ I(0), a = /* @__PURE__ */ I(150), o = /* @__PURE__ */ I(!0);
		async function s() {
			o.value = !0;
			let e = await t.session.read("connections", { filter: n.value });
			e && (r.value = e.connections || [], i.value = e.total || r.value.length, a.value = 150), o.value = !1;
		}
		let c = Z(() => r.value.slice(0, a.value));
		function l(e) {
			return {
				Established: "已连接",
				Listen: "监听中",
				Bound: "等待连接",
				TimeWait: "连接结束",
				CloseWait: "正在关闭",
				SynSent: "正在连接"
			}[e] || e;
		}
		return Nr(s), (e, t) => (U(), W("div", af, [
			K("div", of, [t[2] ||= K("div", null, [K("h2", null, "应用正在连接什么"), K("p", null, "按应用、地址或端口查找当前连接。")], -1), K("span", sf, A(i.value) + " 个连接", 1)]),
			K("form", {
				class: "nx-inline-form nx-searchbar",
				onSubmit: bs(s, ["prevent"])
			}, [K("label", cf, [q(L(fc), { size: 16 }), z(K("input", {
				"onUpdate:modelValue": t[0] ||= (e) => n.value = e,
				class: "nx-input",
				placeholder: "搜索应用、IP 或端口",
				"aria-label": "搜索连接"
			}, null, 512), [[Q, n.value]])]), K("button", {
				class: "btn nx-button btn--secondary",
				disabled: o.value
			}, [q(L(dc), { size: 14 }), t[3] ||= J("刷新 ", -1)], 8, lf)], 32),
			K("section", uf, [o.value ? (U(), W("div", df, [(U(), W(V, null, B(5, (e) => K("div", {
				key: e,
				class: "nx-skeleton nx-skeleton-row"
			})), 64))])) : (U(), W("div", ff, [K("table", pf, [t[4] ||= K("thead", null, [K("tr", null, [
				K("th", null, "应用"),
				K("th", null, "本地端口"),
				K("th", null, "远端地址"),
				K("th", null, "协议"),
				K("th", null, "状态")
			])], -1), K("tbody", null, [(U(!0), W(V, null, B(c.value, (e, t) => (U(), W("tr", { key: t }, [
				K("td", { title: e.path || "" }, [K("strong", null, A(e.process || "未知应用"), 1), e.pid ? (U(), W("small", hf, "PID " + A(e.pid), 1)) : Y("", !0)], 8, mf),
				K("td", null, A(e.local_port), 1),
				K("td", gf, A(e.remote_address ? `${e.remote_address}:${e.remote_port}` : "—"), 1),
				K("td", null, [K("span", _f, A(e.protocol), 1)]),
				K("td", null, [K("span", { class: k(["nx-connection-state", { "is-live": e.state === "Established" }]) }, A(l(e.state)), 3)])
			]))), 128))])]), r.value.length ? Y("", !0) : (U(), W("div", vf, [
				q(L(Bs), { size: 28 }),
				t[5] ||= K("strong", null, "没有匹配的连接", -1),
				t[6] ||= K("p", null, "试着输入其他应用名称、地址或端口。", -1)
			]))])), r.value.length > a.value ? (U(), W("button", {
				key: 2,
				class: "btn nx-button btn--quiet nx-load-more",
				onClick: t[1] ||= (e) => a.value += 150
			}, " 再显示 150 个连接 ")) : Y("", !0)]),
			t[7] ||= K("p", { class: "nx-help" }, "这里显示连接和端口，不代表每个应用的流量大小。", -1)
		]));
	}
}, bf = { class: "nx-view-stack" }, xf = { class: "nx-section-heading" }, Sf = {
	key: 0,
	class: "nx-panel nx-form"
}, Cf = { class: "nx-inline-form" }, wf = { class: "nx-application-actions" }, Tf = ["disabled"], Ef = { class: "nx-inline-form" }, Df = ["disabled"], Of = { class: "nx-panel nx-transaction-list" }, kf = { class: "nx-panel-heading" }, Af = { class: "nx-subtle" }, jf = { class: "nx-transaction-icon" }, Mf = { key: 0 }, Nf = ["disabled", "onClick"], Pf = {
	key: 0,
	class: "nx-empty"
}, Ff = {
	__name: "SecurityView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(!1), r = /* @__PURE__ */ I([]), i = /* @__PURE__ */ I(""), a = /* @__PURE__ */ I(!1), o = /* @__PURE__ */ I("8000000"), s = Z(() => r.value.map((e) => ({
			value: e.path,
			label: `${e.process} · ${e.path.split("\\").at(-1)}`
		}))), c = [
			{
				value: "8000000",
				label: "1 MB/s"
			},
			{
				value: "40000000",
				label: "5 MB/s"
			},
			{
				value: "80000000",
				label: "10 MB/s"
			}
		], l = Z(() => [...t.session.state?.transactions || []].reverse());
		async function u() {
			n.value = !0;
			let e = await t.session.read("connections", {}), i = /* @__PURE__ */ new Set();
			r.value = (e?.connections || []).filter((e) => e.path && !i.has(e.path) && i.add(e.path)).sort((e, t) => (e.process || "").localeCompare(t.process || ""));
		}
		async function d(e) {
			let n = i.value.trim();
			if (!n) {
				t.session.error = "先选择一个应用";
				return;
			}
			await t.session.run("system.apply", {
				kind: e,
				program: n,
				...e === "qos" ? { bits_per_second: Number(o.value) } : {}
			}, e === "qos" ? "已设置应用上传限速" : "已创建应用联网限制");
		}
		function f(e) {
			return {
				proxy: "系统代理",
				dns: "DNS 设置",
				firewall: "应用联网限制",
				qos: "应用上传限速"
			}[e.request?.kind] || "网络设置";
		}
		function p(e) {
			return {
				applied: "正在生效",
				restored: "已恢复",
				prepared: "待核对",
				recovery_required: "需要恢复",
				external_change: "设置已被外部修改",
				failed: "未生效",
				rolled_back: "已撤回"
			}[e] || e;
		}
		return (t, r) => (U(), W("div", bf, [
			K("div", xf, [r[7] ||= K("div", null, [K("h2", null, "应用联网与恢复"), K("p", null, "只修改你选择的应用，随时检查并恢复原设置。")], -1), K("button", {
				class: "btn nx-button btn--secondary",
				onClick: u
			}, [q(L(ic), { size: 15 }), r[6] ||= J("选择应用 ", -1)])]),
			n.value ? (U(), W("section", Sf, [
				r[13] ||= K("h2", null, "管理一个应用", -1),
				K("div", Cf, [a.value ? z((U(), W("input", {
					key: 0,
					"onUpdate:modelValue": r[0] ||= (e) => i.value = e,
					class: "nx-input",
					placeholder: "应用 .exe 的完整路径",
					"aria-label": "应用路径"
				}, null, 512)), [[Q, i.value]]) : (U(), G(ku, {
					key: 1,
					modelValue: i.value,
					"onUpdate:modelValue": r[1] ||= (e) => i.value = e,
					class: "nx-shared-select",
					options: s.value,
					placeholder: "从当前连接的应用中选择",
					"aria-label": "选择应用",
					"data-network-application": "",
					"menu-min-width": 220
				}, null, 8, ["modelValue", "options"])), K("button", {
					class: "btn nx-button btn--quiet",
					onClick: r[2] ||= (e) => {
						a.value = !a.value, i.value = "";
					}
				}, A(a.value ? "从列表选择" : "手动输入路径"), 1)]),
				K("div", wf, [K("div", null, [
					r[9] ||= K("h3", null, "阻止这个应用联网", -1),
					r[10] ||= K("p", null, "创建仅作用于该应用的出站防火墙规则。", -1),
					K("button", {
						class: "btn nx-button btn--secondary nx-danger-text",
						disabled: !i.value || !!e.session.busy,
						onClick: r[3] ||= (e) => d("firewall")
					}, [q(L(hc), { size: 14 }), r[8] ||= J("申请阻止联网 ", -1)], 8, Tf)
				]), K("div", null, [
					r[11] ||= K("h3", null, "限制这个应用的上传", -1),
					r[12] ||= K("p", null, "降低后台上传对其他任务的影响。", -1),
					K("div", Ef, [q(ku, {
						modelValue: o.value,
						"onUpdate:modelValue": r[4] ||= (e) => o.value = e,
						class: "nx-shared-select",
						options: c,
						"aria-label": "应用上传速度上限",
						"data-network-upload-limit": "",
						"menu-min-width": 140
					}, null, 8, ["modelValue"]), K("button", {
						class: "btn nx-button btn--secondary",
						disabled: !i.value || !!e.session.busy,
						onClick: r[5] ||= (e) => d("qos")
					}, " 申请限速 ", 8, Df)])
				])]),
				r[14] ||= K("p", { class: "nx-help" }, " 这两项操作可能需要 Windows 管理员权限，执行前会显示影响范围。 ", -1)
			])) : Y("", !0),
			K("section", Of, [
				K("div", kf, [K("h2", null, [q(L(_c), { size: 17 }), r[15] ||= J("网络设置记录", -1)]), K("span", Af, A(l.value.length) + " 条", 1)]),
				(U(!0), W(V, null, B(l.value, (t) => (U(), W("article", {
					key: t.id,
					class: "nx-transaction"
				}, [
					K("span", jf, [q(L(mc), { size: 18 })]),
					K("div", null, [
						K("strong", null, A(f(t)), 1),
						t.request?.program ? (U(), W("p", Mf, A(t.request.program.split("\\").at(-1)), 1)) : Y("", !0),
						K("small", null, A(L(Sc)(t.time)), 1)
					]),
					K("span", { class: k(["nx-status-text", { "is-warning": ["external_change", "recovery_required"].includes(t.status) }]) }, A(p(t.status)), 3),
					[
						"applied",
						"prepared",
						"recovery_required"
					].includes(t.status) ? (U(), W("button", {
						key: 0,
						class: "btn nx-button btn--secondary",
						disabled: !!e.session.busy,
						onClick: (n) => e.session.run("system.restore", { id: t.id }, "已检查并恢复原设置")
					}, [q(L(_c), { size: 13 }), r[16] ||= J("恢复 ", -1)], 8, Nf)) : Y("", !0)
				]))), 128)),
				l.value.length ? Y("", !0) : (U(), W("div", Pf, [
					q(L(mc), {
						size: 31,
						"stroke-width": 1.4
					}),
					r[17] ||= K("strong", null, "还没有修改网络设置", -1),
					r[18] ||= K("p", null, "通过这里执行的修改，会留下可恢复的记录。", -1)
				]))
			]),
			r[19] ||= K("p", { class: "nx-help" }, " 如果设置已被其他软件或用户修改，会保留当前状态，避免直接覆盖。 ", -1)
		]));
	}
}, If = { class: "nx-view-stack" }, Lf = { class: "nx-panel" }, Rf = { class: "nx-panel-heading" }, zf = ["disabled"], Bf = ["disabled", "onClick"], Vf = ["disabled", "onClick"], Hf = {
	key: 1,
	class: "nx-empty-inline"
}, Uf = { class: "nx-panel" }, Wf = { class: "nx-panel-heading" }, Gf = ["disabled"], Kf = {
	key: 1,
	class: "nx-table-scroll"
}, qf = { class: "nx-table" }, Jf = {
	key: 0,
	class: "nx-empty-inline"
}, Yf = { class: "nx-panel nx-settings-rows" }, Xf = ["disabled"], Zf = {
	key: 0,
	class: "nx-recent"
}, Qf = { class: "nx-section-heading" }, $f = { class: "nx-subtle" }, ep = {
	__name: "AdvancedView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ I(!1), r = /* @__PURE__ */ I("github.com"), i = /* @__PURE__ */ I("30"), a = /* @__PURE__ */ I(null), o = /* @__PURE__ */ I(String(t.session.state?.settings?.sample_seconds || 5)), s = [
			{
				value: "15",
				label: "每 15 分钟"
			},
			{
				value: "30",
				label: "每 30 分钟"
			},
			{
				value: "60",
				label: "每小时"
			},
			{
				value: "360",
				label: "每 6 小时"
			}
		], c = [
			2,
			5,
			10,
			30
		].map((e) => ({
			value: String(e),
			label: `每 ${e} 秒`
		}));
		function l(e) {
			e !== o.value && (o.value = e, t.session.run("settings.update", {
				revision: t.session.state.revision,
				settings: { sample_seconds: Number(e) }
			}, "更新频率已保存"));
		}
		async function u(e) {
			return t.session.run("automation.save", {
				revision: t.session.state.revision,
				automations: e
			}, "定时检查已更新");
		}
		async function d() {
			let e = r.value.trim();
			try {
				e.includes("://") && (e = new URL(e).hostname);
			} catch {
				t.session.error = "请输入有效的网址";
				return;
			}
			await u([...t.session.state.automations || [], {
				target: e,
				action: "diagnose",
				enabled: !0,
				interval_minutes: Number(i.value)
			}]) && (n.value = !1);
		}
		async function f(e) {
			await u(t.session.state.automations.map((t, n) => ({
				...t,
				...n === e ? { enabled: !t.enabled } : {}
			})));
		}
		async function p(e) {
			await u(t.session.state.automations.filter((t, n) => n !== e));
		}
		async function m(e) {
			let n = await t.session.run("automation.run", {
				index: e,
				dry_run: !0
			});
			n && (t.session.notice = `这条计划会检查 ${n.would_execute?.target || ""}，不会修改网络设置。`);
		}
		async function h() {
			let e = await t.session.run("export");
			if (!e) return;
			let n = URL.createObjectURL(new Blob([JSON.stringify(e, null, 2)], { type: "application/json" })), r = document.createElement("a");
			r.href = n, r.download = "network-reports.json", r.click(), setTimeout(() => URL.revokeObjectURL(n), 1e3);
		}
		async function g() {
			a.value = await t.session.read("lan");
		}
		return (t, u) => (U(), W("div", If, [
			K("section", Lf, [
				K("div", Rf, [K("h2", null, [q(L(qs), { size: 17 }), u[3] ||= J("定时检查", -1)]), K("button", {
					class: "btn nx-button btn--quiet",
					onClick: u[0] ||= (e) => n.value = !n.value
				}, [q(L(cc), { size: 14 }), u[4] ||= J("添加 ", -1)])]),
				u[6] ||= K("p", { class: "nx-help" }, "定期检查常用网站，结果会保存在“检测”中。", -1),
				n.value ? (U(), W("form", {
					key: 0,
					class: "nx-inline-form nx-schedule-form",
					onSubmit: bs(d, ["prevent"])
				}, [
					z(K("input", {
						"onUpdate:modelValue": u[1] ||= (e) => r.value = e,
						class: "nx-input",
						required: "",
						placeholder: "检查哪个网站",
						"aria-label": "定时检查的网站"
					}, null, 512), [[Q, r.value]]),
					q(ku, {
						modelValue: i.value,
						"onUpdate:modelValue": u[2] ||= (e) => i.value = e,
						class: "nx-shared-select",
						options: s,
						"aria-label": "检查间隔",
						"data-network-interval": "",
						"menu-min-width": 140
					}, null, 8, ["modelValue"]),
					K("button", {
						class: "btn nx-button btn--secondary",
						disabled: !!e.session.busy
					}, " 添加计划 ", 8, zf)
				], 32)) : Y("", !0),
				(U(!0), W(V, null, B(e.session.state?.automations || [], (t, n) => (U(), W("article", {
					key: n,
					class: "nx-schedule-row"
				}, [
					q(kl, {
						size: "sm",
						label: `${t.target} 定时检查`,
						"model-value": t.enabled,
						disabled: !!e.session.busy,
						"onUpdate:modelValue": (e) => f(n)
					}, null, 8, [
						"label",
						"model-value",
						"disabled",
						"onUpdate:modelValue"
					]),
					K("div", null, [K("strong", null, A(t.target), 1), K("small", null, "每 " + A(t.interval_minutes) + " 分钟检查一次", 1)]),
					K("button", {
						class: "btn nx-button btn--quiet",
						disabled: !!e.session.busy,
						onClick: (e) => m(n)
					}, [q(L(sc), { size: 13 }), u[5] ||= J("试运行", -1)], 8, Bf),
					K("button", {
						class: "btn nx-button btn--quiet nx-icon-button",
						disabled: !!e.session.busy,
						"aria-label": "删除定时检查",
						onClick: (e) => p(n)
					}, [q(L(vc), { size: 14 })], 8, Vf)
				]))), 128)),
				!e.session.state?.automations?.length && !n.value ? (U(), W("p", Hf, " 还没有计划，需要时再添加。 ")) : Y("", !0)
			]),
			K("section", Uf, [
				K("div", Wf, [K("h2", null, [q(L(ic), { size: 17 }), u[7] ||= J("本地设备", -1)]), K("button", {
					class: "btn nx-button btn--quiet",
					onClick: g
				}, " 查看设备 ")]),
				u[9] ||= K("p", { class: "nx-help" }, "查看系统记录过的局域网邻居。", -1),
				a.value ? Y("", !0) : (U(), W("button", {
					key: 0,
					class: "btn nx-button btn--secondary",
					disabled: !!e.session.busy,
					onClick: g
				}, " 读取设备列表 ", 8, Gf)),
				a.value?.devices ? (U(), W("div", Kf, [K("table", qf, [u[8] ||= K("thead", null, [K("tr", null, [
					K("th", null, "设备地址"),
					K("th", null, "硬件地址"),
					K("th", null, "状态")
				])], -1), K("tbody", null, [(U(!0), W(V, null, B(a.value.devices, (e, t) => (U(), W("tr", { key: t }, [
					K("td", null, A(e.IPAddress), 1),
					K("td", null, A(e.LinkLayerAddress || "—"), 1),
					K("td", null, A(e.state), 1)
				]))), 128))])]), a.value.devices.length ? Y("", !0) : (U(), W("p", Jf, " 没有读取到设备记录。 "))])) : Y("", !0)
			]),
			K("section", Yf, [K("div", null, [u[10] ||= K("span", null, [K("strong", null, "网速更新频率"), K("small", null, "降低更新频率可以减少后台采样。")], -1), q(ku, {
				"model-value": o.value,
				options: L(c),
				"aria-label": "网速采样间隔",
				"data-network-sampling": "",
				"menu-min-width": 140,
				"onUpdate:modelValue": l
			}, null, 8, ["model-value", "options"])]), K("div", null, [u[12] ||= K("span", null, [K("strong", null, "导出检查记录"), K("small", null, "保存检查结果和近期事件，方便对照。")], -1), K("button", {
				class: "btn nx-button btn--secondary",
				disabled: !!e.session.busy,
				onClick: h
			}, [q(L(Qs), { size: 14 }), u[11] ||= J("导出 ", -1)], 8, Xf)])]),
			e.session.state?.events?.length ? (U(), W("section", Zf, [K("div", Qf, [u[13] ||= K("h2", null, "活动记录", -1), K("span", $f, "最近 " + A(Math.min(e.session.state.events.length, 40)) + " 条", 1)]), (U(!0), W(V, null, B([...e.session.state.events].reverse().slice(0, 40), (e, t) => (U(), W("div", {
				key: t,
				class: "nx-event"
			}, [
				q(L(Us), { size: 14 }),
				K("span", null, A(e.message), 1),
				K("time", null, A(L(Sc)(e.time)), 1)
			]))), 128))])) : Y("", !0)
		]));
	}
}, tp = ["aria-busy"], np = { class: "nx-sidebar" }, rp = {
	class: "nx-brand",
	title: "EasyNet"
}, ip = { "aria-label": "网络工具" }, ap = [
	"data-page",
	"aria-current",
	"title",
	"onClick"
], op = { class: "nx-sidebar-foot" }, sp = { class: "nx-workspace" }, cp = { class: "nx-header" }, lp = { class: "nx-header-actions" }, up = {
	key: 0,
	class: "nx-working"
}, dp = {
	key: 1,
	class: "nx-live-label"
}, fp = ["disabled"], pp = {
	key: 0,
	class: "nx-notice nx-notice--error",
	role: "alert"
}, mp = ["role"], hp = { class: "nx-content ne-content" }, gp = {
	key: "loading",
	class: "nx-loading",
	"aria-live": "polite"
}, _p = "easynet:page", vp = {
	__name: "NetworkApp",
	props: { context: {
		type: Object,
		required: !0
	} },
	setup(e) {
		let t = Ec(e.context), n = /* @__PURE__ */ I(null), r = [
			{
				id: "home",
				title: "首页",
				hint: "实时数据与常用操作",
				icon: nc,
				component: Yc
			},
			{
				id: "overview",
				title: "加速",
				hint: "本机加速开关与运行状态",
				icon: yc,
				component: wl
			},
			{
				id: "proxy",
				title: "代理",
				hint: "订阅、节点与连接方式",
				icon: tc,
				component: mu
			},
			{
				id: "transfer",
				title: "下载",
				hint: "文件下载与任务",
				icon: Ys,
				component: dd
			},
			{
				id: "diagnose",
				title: "检测",
				hint: "检查网站连接",
				icon: Ls,
				component: jd
			},
			{
				id: "network",
				title: "网络",
				hint: "接口与 DNS",
				icon: pc,
				component: rf
			},
			{
				id: "traffic",
				title: "连接",
				hint: "应用与端口",
				icon: Bs,
				component: yf
			},
			{
				id: "security",
				title: "防护",
				hint: "应用联网与恢复",
				icon: mc,
				component: Ff
			},
			{
				id: "advanced",
				title: "更多",
				hint: "定时检测与记录",
				icon: gc,
				component: ep
			}
		], i = r.filter((e) => [
			"home",
			"overview",
			"proxy",
			"transfer"
		].includes(e.id));
		function a() {
			try {
				let e = sessionStorage.getItem(_p);
				return sessionStorage.removeItem(_p), r.some((t) => t.id === e) ? e : "home";
			} catch {
				return "home";
			}
		}
		let o = /* @__PURE__ */ I(a());
		function s(e) {
			let t = e.detail?.page;
			if (r.some((e) => e.id === t)) {
				l(t);
				try {
					sessionStorage.removeItem(_p);
				} catch {}
			}
		}
		Nr(() => window.addEventListener("sunday:network-plugin-page", s)), Ir(() => window.removeEventListener("sunday:network-plugin-page", s));
		let c = Z(() => r.find((e) => e.id === o.value));
		function l(e) {
			o.value = e, t.notice = "", t.error = "";
		}
		function u(e) {
			n.value = e, o.value = "diagnose";
		}
		return (e, r) => (U(), W("div", {
			class: "nx-app",
			"aria-busy": !!L(t).busy
		}, [K("aside", np, [
			K("div", rp, [q(L(ac), {
				size: 25,
				"stroke-width": 1.7
			}), r[4] ||= K("span", null, "EasyNet", -1)]),
			K("nav", ip, [(U(!0), W(V, null, B(L(i), (e) => (U(), W("button", {
				key: e.id,
				class: k(["nx-nav-item", { "is-active": o.value === e.id }]),
				"data-page": e.id,
				"aria-current": o.value === e.id ? "page" : void 0,
				title: e.hint,
				onClick: (t) => l(e.id)
			}, [(U(), G(Wr(e.icon), {
				size: 20,
				"stroke-width": 1.65
			})), K("span", null, A(e.title), 1)], 10, ap))), 128))]),
			K("div", op, [K("span", { class: k(["nx-live-dot", { "is-offline": !!L(t).connectionError || !L(t).state }]) }, null, 2), K("span", null, A(L(t).connectionError ? "离线" : L(t).state ? "监测中" : "连接中"), 1)])
		]), K("div", sp, [
			K("header", cp, [K("div", null, [
				r[5] ||= K("span", { class: "nx-eyebrow" }, "NETWORK CONSOLE", -1),
				K("h1", null, A(c.value.title), 1),
				K("p", null, A(c.value.hint), 1)
			]), K("div", lp, [L(t).busy ? (U(), W("span", up, "正在处理…")) : L(t).state && !L(t).connectionError ? (U(), W("span", dp, [...r[6] ||= [K("span", { class: "nx-live-dot" }, null, -1), J("实时更新", -1)]])) : Y("", !0), K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				disabled: !!L(t).busy,
				"aria-label": "刷新网络状态",
				onClick: r[0] ||= (e) => L(t).refresh()
			}, [q(L(dc), { size: 17 })], 8, fp)])]),
			L(t).connectionError ? (U(), W("div", pp, [r[7] ||= K("span", null, "暂时无法连接网络服务，请稍后重试。", -1), K("button", {
				class: "btn nx-button btn--quiet",
				onClick: r[1] ||= (e) => L(t).refresh()
			}, "重试")])) : Y("", !0),
			L(t).error || L(t).notice ? (U(), W("div", {
				key: 1,
				class: k(["nx-notice", { "nx-notice--error": L(t).error }]),
				role: L(t).error ? "alert" : "status"
			}, [K("span", null, A(L(t).error || L(t).notice), 1), K("button", {
				class: "btn nx-button btn--quiet nx-icon-button",
				"aria-label": "关闭提示",
				onClick: r[2] ||= (e) => {
					L(t).error = "", L(t).notice = "";
				}
			}, [q(L(vc), { size: 14 })])], 10, mp)) : Y("", !0),
			K("main", hp, [q(po, { name: "nx-page" }, {
				default: jn(() => [L(t).state ? (U(), G(Wr(c.value.component), {
					key: o.value,
					session: L(t),
					report: n.value,
					onNavigate: l,
					onDiagnostic: u
				}, null, 40, ["session", "report"])) : (U(), W("div", gp, [
					r[8] ||= K("div", { class: "nx-skeleton nx-loading-banner" }, null, -1),
					r[9] ||= K("div", { class: "nx-loading-grid" }, [K("div", { class: "nx-skeleton nx-loading-chart" }), K("div", { class: "nx-skeleton nx-loading-chart" })], -1),
					r[10] ||= K("p", null, "正在读取网络状态…", -1),
					L(t).connectionError ? (U(), W("button", {
						key: 0,
						class: "btn nx-button btn--secondary",
						onClick: r[3] ||= (e) => L(t).refresh()
					}, " 重新连接 ")) : Y("", !0)
				]))]),
				_: 1
			})])
		])], 8, tp));
	}
}, yp = {
	class: "nx-app nx-quick-app",
	"aria-label": "网络快捷操作"
}, bp = { class: "nx-pill-list" }, xp = {
	class: "nx-pill-icon",
	title: "加速"
}, Sp = [
	"aria-pressed",
	"aria-label",
	"title",
	"disabled"
], Cp = {
	class: "nx-pill-icon",
	title: "代理"
}, wp = { class: "nx-node-wrap" }, Tp = [
	"aria-pressed",
	"aria-label",
	"title",
	"disabled"
], Ep = {
	class: "nx-quick-pill",
	"data-quick": "download"
}, Dp = {
	class: "nx-pill-icon",
	title: "下载"
}, Op = ["disabled"], kp = {
	key: 0,
	class: "nx-quick-error",
	role: "alert"
}, Ap = {
	key: 1,
	class: "nx-quick-note",
	role: "status"
}, jp = {
	__name: "QuickPanel",
	props: { context: Object },
	setup(e) {
		let t = Object.create(e.context);
		t.compact = !0;
		let n = Ec(t), r = /* @__PURE__ */ I(""), i = Z(() => !!n.state?.proxy?.config_saved), a = Z(() => !!n.state?.proxy?.running), o = Z(() => Object.entries(n.proxy?.proxies || {}).filter(([e, t]) => e !== "GLOBAL" && Array.isArray(t.all) && t.type === "Selector")), s = Z(() => o.value[0] || null), c = Z(() => s.value?.[1]?.all || []), l = Z(() => s.value?.[1]?.now || ""), u = Z(() => c.value.map((e) => ({
			value: e,
			label: e === "DIRECT" ? "直接连接" : e
		}))), d = Z(() => n.systemProxyReady ? n.accelerated ? "已开启" : "未开启" : "读取中");
		function f(e) {
			try {
				sessionStorage.setItem("easynet:page", e);
			} catch {}
			window.dispatchEvent(new CustomEvent("sunday:open-plugin-page", { detail: {
				plugin: "easynet",
				id: "network"
			} })), window.dispatchEvent(new CustomEvent("sunday:network-plugin-page", { detail: { page: e } }));
		}
		function p() {
			if (!i.value) {
				f("proxy");
				return;
			}
			n.toggleProxy();
		}
		async function m(e) {
			!e || !s.value || e === l.value || await n.selectNode(s.value[0], e);
		}
		async function h() {
			let e = r.value.trim();
			await n.run("transfer.add", { url: e }, "已开始下载") && (r.value = "", await n.loadTasks());
		}
		return (e, t) => (U(), W("section", yp, [K("div", bp, [
			K("div", {
				class: k(["nx-quick-pill", { "is-on": L(n).accelerated }]),
				"data-quick": "acceleration"
			}, [
				K("span", xp, [q(L(yc), { size: 16 })]),
				K("span", { class: k(["nx-pill-value", { "is-live": L(n).accelerated }]) }, A(d.value), 3),
				K("button", {
					class: k(["nx-mini-action", { "is-on": L(n).accelerated }]),
					"aria-pressed": L(n).accelerated,
					"aria-label": L(n).accelerated ? "关闭加速" : "开启加速",
					title: L(n).accelerated ? "关闭加速" : "开启加速",
					disabled: !!L(n).busy || !L(n).state || !L(n).systemProxyReady,
					"data-quick-action": "acceleration",
					onClick: t[0] ||= (e) => L(n).toggleAcceleration()
				}, [q(L(lc), { size: 14 })], 10, Sp)
			], 2),
			K("div", {
				class: k(["nx-quick-pill", { "is-on": a.value }]),
				"data-quick": "proxy"
			}, [
				K("span", Cp, [q(L(tc), { size: 16 })]),
				K("div", wp, [q(ku, {
					"model-value": l.value,
					options: u.value,
					disabled: !!L(n).busy || !c.value.length,
					placeholder: "无可用节点",
					"aria-label": "更换节点",
					"data-network-quick-node": "",
					"menu-min-width": 160,
					"onUpdate:modelValue": m
				}, null, 8, [
					"model-value",
					"options",
					"disabled"
				])]),
				K("button", {
					class: k(["nx-mini-action", { "is-on": a.value }]),
					"aria-pressed": a.value,
					"aria-label": a.value ? "关闭代理" : "开启代理",
					title: a.value ? "关闭代理" : "开启代理",
					disabled: !!L(n).busy || !L(n).state,
					"data-quick-action": "proxy",
					onClick: p
				}, [q(L(lc), { size: 14 })], 10, Tp)
			], 2),
			K("div", Ep, [K("span", Dp, [q(L(Ys), { size: 16 })]), K("form", {
				class: "nx-download-form",
				onSubmit: bs(h, ["prevent"])
			}, [z(K("input", {
				"onUpdate:modelValue": t[1] ||= (e) => r.value = e,
				type: "url",
				"aria-label": "下载链接",
				placeholder: "URL",
				required: ""
			}, null, 512), [[Q, r.value]]), K("button", {
				class: k(["nx-mini-action", { "is-ready": r.value.trim() }]),
				disabled: !!L(n).busy || !r.value.trim(),
				"aria-label": "开始下载",
				title: "开始下载"
			}, [q(L(Rs), { size: 14 })], 10, Op)], 32)])
		]), L(n).error || L(n).connectionError ? (U(), W("p", kp, A(L(n).error || "暂时无法连接网络服务"), 1)) : L(n).notice ? (U(), W("p", Ap, A(L(n).notice), 1)) : Y("", !0)]));
	}
}, Mp = ".workspace-main.nx-plugin-full{padding:0!important}.workspace-main.nx-plugin-full>.thread-header[data-full-area-header]{display:none}.workspace-main.nx-plugin-full .split-plugin-page{border-radius:0}.workspace-main.nx-plugin-full .split-content-toolbar{display:none}.workspace-main.nx-plugin-full .split-plugin-page__host{padding:0}.workspace-main.nx-plugin-full .plugin-page-instance,.workspace-main.nx-plugin-full .nx-mount{height:100%;min-height:0}.nx-host>.split-content-toolbar{display:none}.nx-host>.split-plugin-page__host{padding:0}.nx-mount{height:min(780px,76vh);min-height:420px}.nx-host .nx-mount{height:100%;min-height:360px}.nx-mount--quick{height:auto!important;min-height:0!important}.nx-app{--nx-bg:var(--theme-main-background,#111416);--nx-rail:color-mix(in srgb, var(--theme-main-background,#111416) 86%, var(--theme-main-text,#e8eeeb));--nx-panel:color-mix(in srgb, var(--theme-main-background,#111416) 92%, var(--theme-main-text,#e8eeeb));--nx-panel-hover:color-mix(in srgb, var(--theme-main-background,#111416) 84%, var(--theme-main-text,#e8eeeb));--nx-input:color-mix(in srgb, var(--theme-main-background,#111416) 78%, var(--theme-main-text,#e8eeeb));--nx-text:var(--theme-main-text,#e8eeeb);--nx-muted:color-mix(in srgb, var(--theme-main-text,#e8eeeb) 62%, transparent);--nx-faint:color-mix(in srgb, var(--theme-main-text,#e8eeeb) 42%, transparent);--nx-line:var(--theme-main-border,color-mix(in srgb, var(--theme-main-text,#e8eeeb) 14%, transparent));--nx-accent:var(--green,#8ae6bf);--nx-accent-ink:color-mix(in srgb, var(--green,#8ae6bf) 18%, #000);--nx-error:var(--red,#ef9c9f);--nx-warning:var(--orange,var(--nx-warning));background:var(--nx-bg);width:100%;height:100%;min-height:360px;color:var(--nx-text);font-family:var(--font-sans,Inter, \"Segoe UI\", \"Microsoft YaHei\", sans-serif);text-align:left;border-radius:0;font-size:13px;line-height:1.5;display:flex;overflow:hidden;container:nx-shell/inline-size}.nx-app *{box-sizing:border-box}.nx-app button,.nx-app input,.nx-app select,.nx-app textarea{font:inherit}.nx-app button{cursor:pointer}.nx-app button:disabled{cursor:default;opacity:.42}.nx-app svg{vertical-align:middle;flex-shrink:0}.nx-app h1,.nx-app h2,.nx-app h3,.nx-app p{margin:0}.nx-app h2{letter-spacing:-.015em;font-size:14px;font-weight:600;line-height:1.5}.nx-app h3{font-size:13px;font-weight:600}.nx-app button:focus-visible,.nx-app a:focus-visible{outline:2px solid var(--nx-accent);outline-offset:3px}.nx-app input:focus-visible,.nx-app textarea:focus-visible,.nx-app select:focus-visible{outline:1px solid color-mix(in srgb, var(--nx-accent) 65%, transparent);outline-offset:1px}.nx-app ::selection{color:var(--nx-text);background:#315846}.nx-sidebar{background:var(--nx-rail);border-right:1px solid var(--nx-line);flex-direction:column;flex:0 0 88px;align-items:stretch;width:88px;padding:22px 12px 16px;display:flex}.nx-brand{color:var(--nx-accent);flex-direction:column;align-items:center;gap:7px;padding-bottom:24px;display:flex}.nx-brand span{letter-spacing:.02em;color:var(--nx-muted);font-size:10px;font-weight:550}.nx-sidebar nav{flex-direction:column;flex:1;gap:5px;min-height:0;display:flex;overflow-y:auto}.nx-nav-item{min-height:53px;color:var(--nx-muted);background:0 0;border:0;border-radius:11px;flex-direction:column;justify-content:center;align-items:center;gap:5px;transition:background .16s,color .16s;display:flex;position:relative}.nx-nav-item span{font-size:11px}.nx-nav-item:hover{background:color-mix(in srgb, var(--nx-text) 6%, transparent);color:var(--nx-text)}.nx-nav-item.is-active{background:color-mix(in srgb, var(--nx-accent) 11%, transparent);color:var(--nx-accent)}.nx-nav-item.is-active:before{content:\"\";background:var(--nx-accent);border-radius:2px;width:2px;position:absolute;top:13px;bottom:13px;left:0}.nx-nav-divider{background:var(--nx-line);height:1px;margin:14px 8px}.nx-sidebar-foot{color:var(--nx-faint);justify-content:center;align-items:center;gap:6px;margin-top:auto;padding-top:26px;font-size:10px;display:flex}.nx-live-dot{background:var(--nx-accent);border-radius:50%;flex:none;width:6px;height:6px;display:inline-block}.nx-live-dot.is-offline{background:var(--nx-faint)}.nx-workspace{flex-direction:column;flex:1;min-width:0;display:flex;overflow:hidden}.nx-header{border-bottom:1px solid var(--nx-line);flex-shrink:0;justify-content:space-between;align-items:center;gap:16px;padding:22px 30px 18px;display:flex}.nx-header h1{letter-spacing:-.035em;font-size:25px;font-weight:620;line-height:1.3}.nx-header p{color:var(--nx-faint);margin-top:5px;font-size:12px}.nx-header-actions{align-items:center;gap:15px;display:flex}.nx-live-label{color:var(--nx-muted);align-items:center;gap:7px;font-size:11px;display:flex}.nx-working{color:var(--nx-muted);font-size:12px}.nx-content{flex:1;min-height:0;padding:20px 30px 30px;overflow:auto}.nx-content>*{width:100%;min-width:0;max-width:1180px;margin-inline:auto}.nx-eyebrow{color:var(--nx-faint);letter-spacing:.18em;margin-bottom:6px;font-size:9px;font-weight:600;display:block}.nx-page-enter-active,.nx-page-leave-active{transition:opacity .18s,transform .18s}.nx-page-enter-from{opacity:0;transform:translateY(6px)}.nx-page-leave-to{opacity:0;transform:translateY(-4px)}.nx-home{flex-direction:column;gap:16px;display:flex}.nx-stat-bar{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:16px;grid-template-columns:repeat(4,minmax(0,1fr));display:grid;overflow:hidden}.nx-stat{flex-direction:column;gap:5px;min-width:0;padding:15px 20px;display:flex}.nx-stat+.nx-stat{border-left:1px solid var(--nx-line)}.nx-stat>span{color:var(--nx-muted);align-items:center;gap:6px;font-size:11px;display:flex}.nx-stat>strong{font-variant-numeric:tabular-nums;letter-spacing:-.025em;text-overflow:ellipsis;white-space:nowrap;font-size:20px;font-weight:600;overflow:hidden}.nx-stat[data-stat=download]>strong{color:var(--nx-accent)}.nx-home-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;display:grid}.nx-quick-card{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:18px;flex-direction:column;gap:15px;min-height:236px;padding:20px;transition:border-color .18s;display:flex}.nx-quick-card.is-on{border-color:color-mix(in srgb, var(--nx-accent) 34%, var(--nx-line))}.nx-quick-head{align-items:center;gap:10px;min-width:0;display:flex}.nx-quick-icon{background:var(--nx-input);width:38px;height:38px;color:var(--nx-muted);border-radius:12px;flex:0 0 38px;place-items:center;display:grid}.nx-route-icon{background:color-mix(in srgb, var(--nx-accent) 12%, transparent);width:38px;height:38px;color:var(--nx-accent);border-radius:12px;flex:0 0 38px;place-items:center;display:grid}.nx-quick-card.is-on .nx-quick-icon{background:color-mix(in srgb, var(--nx-accent) 14%, transparent);color:var(--nx-accent)}.nx-quick-title{flex:1;min-width:0}.nx-quick-title h2{font-size:14px}.nx-quick-title p{color:var(--nx-faint);margin-top:1px;font-size:10px}.nx-quick-state{border:1px solid var(--nx-line);color:var(--nx-muted);white-space:nowrap;border-radius:999px;padding:3px 8px;font-size:10px}.nx-quick-state.is-live{background:color-mix(in srgb, var(--nx-accent) 14%, transparent);color:var(--nx-accent);border-color:#0000}.nx-quick-main{flex-direction:column;gap:3px;min-width:0;display:flex}.nx-quick-main>strong{letter-spacing:-.02em;text-overflow:ellipsis;white-space:nowrap;font-size:16px;font-weight:600;overflow:hidden}.nx-quick-main>p{color:var(--nx-muted);text-overflow:ellipsis;white-space:nowrap;font-size:11px;overflow:hidden}.nx-quick-actions{align-items:center;gap:8px;margin-top:auto;display:flex}.nx-quick-actions>.nx-button:first-child{flex:1;min-height:38px}.nx-quick-link{color:var(--nx-muted);gap:3px;padding-inline:8px;font-size:11px}.nx-quick-actions--stack{flex-direction:column;align-items:stretch;gap:6px}.nx-home-download{gap:8px;min-width:0;display:flex}.nx-home-download>.nx-input{flex:1;min-width:0;min-height:38px}.nx-home-download>.nx-button{border-radius:var(--radius-sm,6px);gap:7px;min-height:34px;padding:7px 12px;font-size:12px;font-weight:550;line-height:1.4}.nx-button svg{stroke-width:1.7px}.nx-icon-button{min-width:32px;min-height:32px;padding:6px}.nx-danger-text{color:var(--nx-error)}.nx-actions{flex-wrap:wrap;align-items:center;gap:8px;display:flex}.nx-notice{background:color-mix(in srgb, var(--nx-accent) 9%, var(--nx-panel));color:var(--nx-text);border:1px solid var(--nx-line);border-radius:10px;flex-shrink:0;justify-content:space-between;align-items:center;gap:12px;margin:0 30px 18px;padding:10px 12px;font-size:12px;display:flex}.nx-notice--error{color:var(--nx-error);background:#2e2023;border-color:#4b3037}.nx-notice>span{overflow-wrap:anywhere;min-width:0}.nx-notice .nx-button{color:inherit;flex-shrink:0}.nx-acceleration{background:color-mix(in srgb, var(--nx-accent) 7%, var(--nx-panel));align-items:center;gap:17px;padding:23px 24px;display:flex}.nx-acceleration-icon{background:color-mix(in srgb, var(--nx-accent) 10%, var(--nx-panel));width:52px;height:52px;color:var(--nx-muted);border-radius:16px;flex:0 0 52px;place-items:center;display:grid}.nx-acceleration-icon.is-on{color:var(--nx-accent);background:#294d3a}.nx-acceleration-copy{flex:1;min-width:0}.nx-acceleration-copy h2{align-items:center;gap:10px;font-size:17px;font-weight:600;display:flex}.nx-acceleration-copy p{color:var(--nx-muted);overflow-wrap:anywhere;margin-top:6px;font-size:12px}.nx-badge{border:1px solid var(--nx-line);color:var(--nx-muted);white-space:nowrap;border-radius:6px;padding:2px 7px;font-size:10px;font-weight:450}.nx-badge.is-on{color:var(--nx-accent);background:#233a2d;border-color:#3e5c4a}.nx-acceleration>.nx-button{min-height:39px;padding-inline:16px}.nx-node-toolbar{justify-content:space-between;align-items:center;gap:12px;margin:-2px 0 10px;display:flex}.nx-optimize{white-space:nowrap;margin-left:auto}.nx-node-head-actions{align-items:center;gap:6px;display:flex}.nx-line-groups{flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:12px;display:flex}.nx-line-group{border:1px solid var(--nx-line);color:var(--nx-muted);background:0 0;border-radius:999px;padding:6px 12px;font-size:11px;transition:background .16s,border-color .16s,color .16s}.nx-line-group:hover{background:var(--nx-panel-hover);color:var(--nx-text)}.nx-line-group.is-active{border-color:color-mix(in srgb, var(--nx-accent) 42%, var(--nx-line));background:color-mix(in srgb, var(--nx-accent) 10%, transparent);color:var(--nx-text)}.nx-line-groups .nx-subtle{margin-left:auto}.nx-line-list{flex-direction:column;max-height:430px;margin:0 -8px;display:flex;overflow:auto}.nx-line-row{border-bottom:1px solid var(--nx-line);align-items:center;gap:6px;display:flex}.nx-line-row:last-child{border-bottom:0}.nx-line-choice{min-width:0;color:var(--nx-text);text-align:left;background:0 0;border:0;border-radius:10px;flex:1;align-items:center;gap:12px;padding:13px 8px;display:flex}.nx-line-choice:hover{background:var(--nx-panel-hover)}.nx-line-row.is-selected .nx-line-choice{background:color-mix(in srgb, var(--nx-accent) 7%, transparent)}.nx-line-radio{border:1px solid var(--nx-line);width:16px;height:16px;color:var(--nx-accent-ink);border-radius:50%;flex:0 0 16px;place-items:center;display:grid}.nx-line-row.is-selected .nx-line-radio{border-color:var(--nx-accent);background:var(--nx-accent)}.nx-line-name{text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;font-size:13px;overflow:hidden}.nx-line-exit{text-overflow:ellipsis;white-space:nowrap;flex:0 auto;max-width:34%;font-size:11px;overflow:hidden}.nx-line-meter{background:var(--nx-line);border-radius:999px;flex:0 0 120px;width:120px;height:4px;overflow:hidden}.nx-line-meter i{border-radius:inherit;background:var(--nx-accent);height:100%;transition:width .3s;display:block}.nx-line-meter.is-mid i{background:var(--nx-warning)}.nx-line-meter.is-slow i{background:var(--nx-error)}.nx-line-meter.is-unknown i{background:var(--nx-faint)}.nx-line-ms{width:62px;color:var(--nx-muted);font-variant-numeric:tabular-nums;text-align:right;flex:0 0 62px;font-size:11px}.nx-line-refresh{opacity:.35}.nx-line-row:hover .nx-line-refresh,.nx-line-row.is-selected .nx-line-refresh{opacity:1}.nx-node-list{max-height:380px;margin-inline:-8px;overflow:auto}.nx-node-list--compact{max-height:206px}.nx-node{border-radius:9px;align-items:center;min-width:0;display:flex}.nx-node:hover{background:color-mix(in srgb, var(--nx-text) 4%, transparent)}.nx-node.is-selected{background:#25352b}.nx-node-choice{text-align:left;width:100%;min-width:0;min-height:43px;color:var(--nx-text);background:0 0;border:0;border-radius:9px;align-items:center;gap:11px;padding:10px 9px;display:flex}.nx-node-name{text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:13px;overflow:hidden}.nx-node-delay{color:var(--nx-faint);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:11px}.is-selected .nx-node-delay{color:#91b69e}.nx-radio-mark{border:1px solid #4d5a52;border-radius:50%;flex-shrink:0;place-items:center;width:16px;height:16px;display:grid}.is-selected .nx-radio-mark{background:var(--nx-accent);border-color:var(--nx-accent);color:var(--nx-accent-ink)}.nx-node-search{margin-bottom:10px}.nx-add-profile{margin-top:13px;padding-inline:4px;font-size:11px}.nx-select-wrap{align-items:center;gap:6px;min-width:0;display:flex;position:relative}.nx-select-wrap select{appearance:none;color:var(--nx-text);outline-offset:3px;cursor:pointer;background:0 0;border:0;max-width:220px;padding:1px 20px 1px 0;font-size:12px}.nx-select-wrap svg{pointer-events:none;color:var(--nx-faint);position:absolute;right:0}.nx-select-wrap option{background:var(--nx-panel);color:var(--nx-text)}.nx-speed{flex-direction:column;padding-bottom:15px;display:flex}.nx-speed-values{flex-wrap:wrap;gap:30px;margin-top:3px;display:flex}.nx-speed-values>span{align-items:center;gap:7px;min-width:0;display:flex}.nx-speed-values strong{letter-spacing:-.025em;font-variant-numeric:tabular-nums;font-size:19px;font-weight:550}.nx-speed-values small{color:var(--nx-faint);padding-top:4px;font-size:10px}.nx-speed-values>span:first-child>svg{color:var(--nx-accent)}.nx-speed-values>span:nth-child(2)>svg{color:var(--blue,#a2b8c6)}.nx-plot{min-height:153px;color:var(--nx-accent);flex:1;margin:17px -6px 0}.nx-plot>svg{width:100%;height:100%;overflow:visible}.nx-chart-grid{stroke:var(--nx-line);stroke-width:1px;fill:none;vector-effect:non-scaling-stroke}.nx-chart-area{stroke:none}.nx-chart-download{stroke:var(--nx-accent);stroke-width:2px;stroke-linejoin:round;stroke-linecap:round;fill:none;vector-effect:non-scaling-stroke}.nx-chart-upload{stroke:var(--blue,#8a9ca5);stroke-width:1.5px;stroke-dasharray:4 5;fill:none;vector-effect:non-scaling-stroke;opacity:.65}.nx-chart-axis{color:var(--nx-faint);justify-content:space-between;gap:10px;margin-top:8px;font-size:10px;display:flex}.nx-chart-wait{height:100%;color:var(--nx-faint);flex-direction:column;justify-content:center;align-items:center;gap:6px;font-size:12px;display:flex}.nx-chart-wait small{color:var(--nx-faint);font-size:11px}.nx-mode-options{flex-direction:column;gap:5px;display:flex}.nx-mode{width:100%;color:var(--nx-muted);text-align:left;background:0 0;border:1px solid #0000;border-radius:10px;align-items:center;gap:11px;min-width:0;padding:10px 8px;display:flex}.nx-mode:hover:not(:disabled){background:var(--nx-line)}.nx-mode[aria-checked=true]{color:var(--nx-text);background:#28372d;border-color:#3d5143}.nx-mode>span:nth-child(2){flex:1;gap:3px;min-width:0;display:grid}.nx-mode strong{font-size:12px;font-weight:550}.nx-mode small{color:var(--nx-faint);font-size:10px;line-height:1.5}.nx-mode-dot{border:1px solid #5c6c61;border-radius:50%;flex-shrink:0;width:13px;height:13px}.nx-mode[aria-checked=true] .nx-mode-dot{border:4px solid var(--nx-accent)}.nx-modes>.nx-help{margin-top:10px;font-size:11px}.nx-local-info>strong{color:var(--nx-muted);font-size:12px;font-weight:500}.nx-address{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;letter-spacing:-.015em;margin:7px 0 10px;font-size:18px;font-weight:500}.nx-local-info>.nx-button{padding-left:0;font-size:11px}.nx-total>div:not(.nx-panel-heading){justify-content:space-between;align-items:center;gap:12px;margin-top:11px;display:flex}.nx-total>div>span{color:var(--nx-muted);align-items:center;gap:6px;font-size:12px;display:flex}.nx-total strong{font-variant-numeric:tabular-nums;font-size:14px;font-weight:500}.nx-total>.nx-help{color:var(--nx-faint);margin-top:15px;font-size:10px}.nx-input{border:1px solid var(--nx-line);background:var(--nx-input);width:100%;min-width:0;min-height:38px;color:var(--nx-text);accent-color:var(--nx-accent);border-radius:9px;padding:9px 12px;font-size:12px;line-height:1.5}.nx-input::placeholder{color:#839188;opacity:1}.nx-input option{background:var(--nx-panel);color:var(--nx-text)}.nx-inline-form{align-items:center;gap:10px;min-width:0;display:flex}.nx-inline-form>.nx-shared-select{flex:1;min-width:0}.nx-inline-form>.nx-input{flex:1}.nx-inline-form>.nx-button{flex-shrink:0;min-height:38px}.nx-input-with-icon,.nx-input-with-action{flex:1;align-items:center;min-width:0;display:flex;position:relative}.nx-input-with-icon>svg{color:var(--nx-faint);pointer-events:none;position:absolute;left:12px}.nx-input-with-icon>.nx-input{padding-left:38px}.nx-input-with-action>.nx-input{padding-right:42px}.nx-input-with-action>.nx-button{position:absolute;right:4px}.nx-fit-select{min-width:100px;flex:0 auto!important;width:auto!important}.nx-form{gap:15px;display:grid}.nx-form>.nx-button{justify-self:start}.nx-form-grid{grid-template-columns:1fr 1fr;gap:16px;display:grid}.nx-form-grid>:is(label,.nx-form-field){gap:7px;min-width:0;display:grid}.nx-form-grid>:is(label,.nx-form-field)>span{color:var(--nx-muted);font-size:12px}.nx-code{resize:vertical;font-family:Cascadia Code,Consolas,monospace;font-size:12px;line-height:1.7}.nx-import>.nx-help{margin-bottom:13px}.nx-import-options{flex-wrap:wrap;gap:14px;margin-top:8px;display:flex}.nx-import-options>.nx-button{padding-left:0;font-size:11px}.nx-import>.nx-form{margin-top:12px}.nx-import-running{justify-content:space-between;align-items:center;gap:12px;margin-top:14px;display:flex}.nx-import-running .nx-button{font-size:11px}.nx-import>.nx-help:last-child{margin-top:12px;margin-bottom:0}.nx-site-shortcuts{flex-wrap:wrap;align-items:center;gap:4px;margin-top:8px;display:flex}.nx-site-shortcuts>span{color:var(--nx-faint);margin-right:4px;font-size:10px}.nx-site-shortcuts .nx-button{min-height:27px;padding:4px 6px;font-size:10px}.nx-recent{padding:18px 20px}.nx-recent>.nx-section-heading{margin-bottom:9px}.nx-event{border-bottom:1px solid #252e28;align-items:center;gap:11px;padding:11px 0;font-size:12px;display:flex}.nx-event>svg{color:var(--nx-faint)}.nx-event>span{overflow-wrap:anywhere;flex:1;min-width:0}.nx-event>time{color:var(--nx-faint);white-space:nowrap;font-size:10px}.nx-event:last-child{border-bottom:0;padding-bottom:0}.nx-empty{text-align:center;color:var(--nx-faint);flex-direction:column;justify-content:center;align-items:center;gap:11px;padding:52px 20px;display:flex}.nx-empty>svg{color:#83968a;margin-bottom:3px}.nx-empty>strong{color:var(--nx-text);font-size:14px;font-weight:500}.nx-empty>p{max-width:35ch;color:var(--nx-muted);font-size:12px;line-height:1.7}.nx-empty>.nx-button{margin-top:5px}.nx-empty--small{padding:27px 10px}.nx-empty--small strong{font-size:12px}.nx-empty--small p{font-size:11px}.nx-control-row{align-items:center;gap:15px;display:flex}.nx-control-row--plain{padding:0}.nx-control-icon{color:#bfd0c4;background:#28322b;border-radius:11px;flex:0 0 40px;place-items:center;width:40px;height:40px;display:grid}.nx-control-copy{flex:1;min-width:0}.nx-control-copy strong{font-size:13px;font-weight:550}.nx-control-copy p{color:var(--nx-muted);margin-top:4px;font-size:11px;line-height:1.6}.nx-settings-fold{padding-top:3px}.nx-settings-fold>.nx-panel{margin-top:12px}.nx-detail-list{max-width:650px;margin:12px 0}.nx-detail-list>div{border-bottom:1px solid var(--nx-line);color:var(--nx-muted);justify-content:space-between;gap:15px;padding:10px 0;font-size:12px;display:flex}.nx-detail-list>div>span:last-child{align-items:center;gap:5px;display:flex}.nx-detail-list code{color:var(--nx-text);font-size:11px}.nx-download-composer>.nx-inline-form{margin-bottom:5px}.nx-download-stats{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:14px;grid-template-columns:repeat(3,minmax(0,1fr));display:grid;overflow:hidden}.nx-download-stats>div{justify-content:space-between;align-items:baseline;gap:10px;padding:12px 18px;display:flex}.nx-download-stats>div+div{border-left:1px solid var(--nx-line)}.nx-download-stats span{color:var(--nx-muted);font-size:11px}.nx-download-stats strong{font-variant-numeric:tabular-nums;font-size:15px;font-weight:600}.nx-download-composer.is-dragging{border-color:color-mix(in srgb, var(--nx-accent) 55%, var(--nx-line));background:color-mix(in srgb, var(--nx-accent) 7%, var(--nx-panel))}.nx-download-options{flex-wrap:wrap;gap:8px 18px;margin:9px 0 4px;display:flex}.nx-download-options>:is(label,.nx-download-option){color:var(--nx-muted);align-items:center;gap:8px;font-size:11px;display:flex}.nx-download-options select{border:1px solid var(--nx-line);background:var(--nx-input);min-height:30px;color:var(--nx-text);border-radius:8px;padding:4px 8px;font-size:11px}.nx-options-button{padding-left:0;font-size:11px}.nx-download-composer>.nx-form-grid{padding-top:13px}.nx-checkbox{align-self:end;align-items:center;min-height:38px;gap:8px!important;display:flex!important}.nx-checkbox>input{accent-color:var(--nx-accent)}.nx-list-toolbar{justify-content:space-between;align-items:center;gap:12px;display:flex}.nx-filter-tabs{align-items:center;gap:5px;display:flex}.nx-filter-tabs>button{min-height:32px;color:var(--nx-muted);background:0 0;border:0;border-radius:8px;align-items:center;gap:7px;padding:6px 10px;font-size:12px;display:flex}.nx-filter-tabs>button.active{color:var(--nx-text);background:#29332c}.nx-filter-tabs>button:hover{background:#242e27}.nx-filter-tabs>button>span{color:var(--nx-faint);font-size:10px}.nx-task-list{padding:0 20px}.nx-download-row{border-bottom:1px solid var(--nx-line);grid-template-columns:40px minmax(0,1fr) auto;align-items:center;column-gap:15px;padding:23px 0;display:grid}.nx-download-row:last-child{border-bottom:0}.nx-file-icon{color:#b3d5bd;background:#29352c;border-radius:10px;place-items:center;width:40px;height:45px;display:grid}.nx-download-body{min-width:0}.nx-task-title{justify-content:space-between;align-items:baseline;gap:12px;min-width:0;display:flex}.nx-task-title>strong{text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:500;overflow:hidden}.nx-task-title>span{color:var(--nx-muted);white-space:nowrap;font-size:10px}.nx-progress-track{background:#313b34;border-radius:99px;height:4px;margin:10px 0 8px;overflow:hidden}.nx-progress-track>span{background:var(--nx-accent);border-radius:inherit;height:100%;transition:width .25s;display:block}.nx-task-meta{color:var(--nx-faint);font-variant-numeric:tabular-nums;flex-wrap:wrap;justify-content:space-between;gap:10px;font-size:10px;display:flex}.nx-meta-divider{color:var(--nx-faint);margin-inline:6px}.nx-task-controls{align-items:center;gap:5px;display:flex}.nx-task-details{grid-column:2/-1;gap:13px;padding:17px 0 0;display:grid}.nx-task-details>.nx-subtle{overflow-wrap:anywhere;font-size:11px}.nx-small-select{color:var(--nx-muted);align-items:center;gap:8px;font-size:11px;display:flex}.nx-small-select select{background:var(--nx-input);border:1px solid var(--nx-line);min-height:30px;color:var(--nx-text);border-radius:7px;padding:4px 7px}.nx-state-error{color:var(--nx-error)!important}.nx-diagnose-start{text-align:center;padding:30px 28px 23px}.nx-diagnose-symbol{width:49px;height:49px;color:var(--nx-accent);background:#2a3d30;border-radius:15px;place-items:center;margin:0 auto 15px;display:grid}.nx-diagnose-start>h2{letter-spacing:-.025em;font-size:19px;font-weight:550}.nx-diagnose-start>p{color:var(--nx-muted);margin-top:7px;font-size:12px}.nx-diagnose-start>.nx-inline-form{max-width:580px;margin:22px auto 0}.nx-diagnose-options{color:var(--nx-muted);flex-wrap:wrap;justify-content:center;align-items:center;gap:20px;margin-top:17px;font-size:11px;display:flex}.nx-diagnose-options>label{cursor:pointer;align-items:center;gap:5px;display:flex}.nx-diagnose-options input{accent-color:var(--nx-accent);width:12px;height:12px;margin:0}.nx-report-heading{align-items:center;gap:14px;margin-bottom:20px;display:flex}.nx-result-icon{width:44px;height:44px;color:var(--nx-accent);background:#273f2f;border-radius:13px;place-items:center;display:grid}.nx-result-icon.is-failure{color:var(--nx-warning);background:#3c3324}.nx-report-heading h2{font-size:16px}.nx-report-heading p{color:var(--nx-muted);margin-top:4px;font-size:11px}.nx-check-list{gap:0;display:grid}.nx-check-row{border-bottom:1px solid var(--nx-line);grid-template-columns:20px minmax(0,1fr) auto 66px;align-items:center;gap:11px;min-height:47px;display:grid}.nx-check-row:last-child{border-bottom:0}.nx-check-status{width:18px;height:18px;color:var(--nx-accent);border:1px solid #3f5b49;border-radius:50%;place-items:center;display:grid}.nx-check-status.is-failure{color:var(--nx-error);border-color:#70504d}.nx-check-row strong{font-size:12px;font-weight:450}.nx-check-row>span:not(.nx-check-status){color:var(--nx-muted);font-size:11px}.nx-check-row time{color:var(--nx-faint);text-align:right;font-variant-numeric:tabular-nums;font-size:11px}.nx-report-advice{color:var(--nx-muted);font-size:12px;line-height:1.8;margin-top:17px!important}.nx-report-detail-button{margin-top:10px;padding-left:0;font-size:11px}.nx-check-evidence{gap:14px;margin-top:10px;display:grid}.nx-check-evidence>div{background:var(--nx-input);border-radius:9px;min-width:0;padding:12px}.nx-check-evidence strong{color:var(--nx-muted);font-size:11px;font-weight:500}.nx-check-evidence p{overflow-wrap:anywhere;white-space:pre-wrap;color:var(--nx-faint);margin-top:6px;font-size:11px;line-height:1.7}.nx-history>.nx-section-heading{padding-bottom:10px}.nx-history-row{border:0;border-bottom:1px solid var(--nx-line);text-align:left;width:100%;color:var(--nx-text);background:0 0;align-items:center;gap:12px;padding:13px 2px;display:flex}.nx-history-row:hover{background:color-mix(in srgb, var(--nx-text) 3%, transparent)}.nx-history-row>strong{text-overflow:ellipsis;flex:1;min-width:0;font-size:12px;font-weight:500;overflow:hidden}.nx-history-row>span:not(.nx-history-result),.nx-history-row>time{color:var(--nx-faint);font-size:10px}.nx-history-result{color:var(--nx-accent)}.nx-history-result.is-failure{color:var(--nx-warning)}.nx-diagnose-empty{padding-block:28px;font-size:12px}.nx-diagnose-pending>p{color:var(--nx-muted);margin-block:15px;font-size:12px}.nx-skeleton{background:linear-gradient(100deg, var(--nx-line) 20%, #303b33 45%, var(--nx-line) 70%);background-size:220% 100%;border-radius:8px;animation:1.6s infinite nx-loading-sheen}.nx-skeleton-title{width:180px;height:15px}.nx-skeleton-row{width:100%;height:35px;margin-block:10px}.nx-loading-banner{height:100px}.nx-loading-grid{grid-template-columns:1.7fr 1fr;gap:20px;margin-top:20px;display:grid}.nx-loading-chart{height:250px}.nx-loading>p{color:var(--nx-muted);margin-top:18px;font-size:12px}.nx-loading>.nx-button{margin-top:14px}.nx-interface-list{padding-block:0}.nx-interface{border-bottom:1px solid var(--nx-line);grid-template-columns:40px minmax(0,1fr);gap:16px;padding:22px 0;display:grid}.nx-interface:last-child{border:0}.nx-interface strong{font-size:13px;font-weight:500}.nx-interface dl{gap:7px;margin:10px 0 0;display:grid}.nx-interface dl>div{gap:18px;min-width:0;font-size:11px;display:flex}.nx-interface dt{min-width:52px;color:var(--nx-faint)}.nx-interface dd{color:var(--nx-muted);overflow-wrap:anywhere;margin:0}.nx-query-result{border-top:1px solid var(--nx-line);padding-top:14px}.nx-query-address{font-variant-numeric:tabular-nums;margin-top:8px;font-size:13px}.nx-rule-row{grid-template-columns:minmax(0,1fr) minmax(100px,.65fr) 30px;gap:8px;display:grid}.nx-table-panel{padding:0;overflow:hidden}.nx-table-scroll{max-width:100%;overflow:auto}.nx-table{border-collapse:collapse;white-space:nowrap;text-align:left;width:100%;font-size:12px}.nx-table th{color:var(--nx-faint);border-bottom:1px solid var(--nx-line);padding:13px 17px;font-size:10px;font-weight:450}.nx-table td{color:var(--nx-muted);border-bottom:1px solid #29312c;padding:14px 17px}.nx-table tr:last-child td{border-bottom:0}.nx-table td strong{color:var(--nx-text);text-overflow:ellipsis;max-width:180px;font-size:12px;font-weight:500;display:block;overflow:hidden}.nx-table td small{color:var(--nx-faint);margin-top:3px;font-size:10px;display:block}.nx-table tbody tr:hover{background:#202822}.nx-table .nx-data-cell{font-variant-numeric:tabular-nums;font-size:11px}.nx-protocol{color:var(--nx-faint);border:1px solid #39433c;border-radius:4px;padding:2px 5px;font-size:10px}.nx-connection-state{color:var(--nx-faint);font-size:11px}.nx-connection-state.is-live{color:#9bc9ac}.nx-table-loading{padding:10px 18px}.nx-load-more{border-top:1px solid var(--nx-line);border-radius:0;width:100%;min-height:39px;font-size:11px}.nx-application-actions{grid-template-columns:1fr 1fr;gap:24px;padding-block:8px;display:grid}.nx-application-actions p{color:var(--nx-muted);margin:6px 0 13px;font-size:11px}.nx-transaction-list>.nx-panel-heading{margin-bottom:5px}.nx-transaction{border-bottom:1px solid var(--nx-line);align-items:center;gap:13px;padding:16px 0;display:flex}.nx-transaction:last-child{border-bottom:0}.nx-transaction-icon{color:var(--nx-faint)}.nx-transaction>div{overflow-wrap:anywhere;flex:1;min-width:0}.nx-transaction strong{font-size:12px;font-weight:500}.nx-transaction p,.nx-transaction small{color:var(--nx-faint);margin-top:3px;font-size:10px;display:block}.nx-status-text{color:var(--nx-muted);white-space:nowrap;font-size:10px}.nx-status-text.is-warning{color:var(--nx-warning)}.nx-schedule-form{margin-top:15px}.nx-schedule-row{border-bottom:1px solid var(--nx-line);align-items:center;gap:12px;padding:15px 0;display:flex}.nx-schedule-row:last-child{border-bottom:0}.nx-schedule-row>div{flex:1;min-width:0}.nx-schedule-row strong{overflow-wrap:anywhere;font-size:12px;font-weight:500}.nx-schedule-row small{color:var(--nx-faint);margin-top:4px;font-size:10px;display:block}.nx-settings-rows{padding-block:0}.nx-settings-rows>div{border-bottom:1px solid var(--nx-line);justify-content:space-between;align-items:center;gap:24px;padding:20px 0;display:flex}.nx-settings-rows>div:last-child{border:0}.nx-settings-rows strong{font-size:12px;font-weight:500;display:block}.nx-settings-rows small{color:var(--nx-muted);margin-top:5px;font-size:11px;display:block}.nx-host .plugin-page-instance{height:100%}.nx-quick-app{--nx-text:var(--theme-backdrop-text,var(--theme-main-text,#e8eeeb));--nx-muted:color-mix(in srgb, var(--nx-text) 60%, transparent);--nx-faint:color-mix(in srgb, var(--nx-text) 40%, transparent);--nx-line:color-mix(in srgb, var(--nx-text) 11%, transparent);--nx-accent:var(--green,#8ae6bf);--nx-accent-ink:color-mix(in srgb, var(--green,#8ae6bf) 18%, #000);--nx-panel:transparent;--nx-panel-hover:color-mix(in srgb, var(--nx-text) 7%, transparent);--nx-input:color-mix(in srgb, var(--nx-text) 5%, transparent);background:0 0;border:0;border-radius:0;width:100%;max-width:100%;height:auto;min-height:0;padding:0;display:block;overflow:visible}.nx-pill-list{flex-direction:column;gap:8px;display:flex}.nx-quick-pill{border:1px solid color-mix(in srgb, var(--nx-text) 9%, transparent);background:color-mix(in srgb, var(--nx-text) 4%, transparent);width:100%;min-height:46px;box-shadow:inset 0 1px 0 color-mix(in srgb, var(--nx-text) 5%, transparent);color:var(--nx-text);border-radius:999px;align-items:center;gap:8px;padding:6px 8px 6px 10px;transition:border-color .16s,background .16s;display:flex}.nx-quick-pill:focus-within{border-color:color-mix(in srgb, var(--nx-accent) 42%, var(--nx-line))}.nx-quick-pill.is-on{border-color:color-mix(in srgb, var(--nx-accent) 30%, transparent);background:color-mix(in srgb, var(--nx-accent) 6%, transparent)}.nx-pill-icon{background:color-mix(in srgb, var(--nx-text) 6%, transparent);width:30px;height:30px;color:var(--nx-muted);border-radius:50%;flex:0 0 30px;place-items:center;display:grid}.nx-quick-pill.is-on .nx-pill-icon{background:color-mix(in srgb, var(--nx-accent) 13%, transparent);color:var(--nx-accent)}.nx-pill-value{min-width:0;color:var(--nx-muted);font-variant-numeric:tabular-nums;letter-spacing:-.01em;flex:1;font-size:11px}.nx-pill-value.is-live{color:var(--nx-accent)}.nx-mini-action{border:1px solid var(--nx-line);width:32px;height:32px;color:var(--nx-muted);background:0 0;border-radius:50%;flex:0 0 32px;place-items:center;padding:0;transition:border-color .16s,background .16s,color .16s;display:grid}.nx-mini-action:hover:not(:disabled){border-color:color-mix(in srgb, var(--nx-accent) 36%, var(--nx-line));color:var(--nx-text)}.nx-mini-action.is-on,.nx-mini-action.is-ready{background:var(--nx-accent);color:var(--nx-accent-ink);border-color:#0000}.nx-mini-action:disabled{opacity:.38}.nx-node-wrap{flex:1;align-items:center;min-width:0;display:flex;position:relative}.nx-quick-app .nx-node-wrap .ui-select{width:100%}.nx-quick-app .nx-node-wrap .ui-select-trigger{min-height:32px;color:var(--nx-text);background:0 0;border:0;padding-left:2px;font-size:11px}.nx-download-form{flex:1;align-items:center;gap:6px;min-width:0;display:flex}.nx-download-form>input{min-width:0;height:32px;color:var(--nx-text);background:0 0;border:0;outline:none;flex:1;padding:0 2px;font-size:11px}.nx-download-form>input::placeholder{color:var(--nx-faint)}.nx-quick-error,.nx-quick-note{overflow-wrap:anywhere;font-size:10px;line-height:1.5;margin:8px 4px 0!important}.nx-quick-error{color:var(--nx-error)}.nx-quick-note{color:var(--nx-accent)}@keyframes nx-loading-sheen{to{background-position:-220% 0}}@container nx-shell (width<=850px){.nx-sidebar{flex-basis:76px;width:76px;padding-inline:9px}.nx-header{padding:23px 22px 20px}.nx-content{padding:0 22px 24px}.nx-notice{margin-inline:22px}.nx-panel{padding:17px}.nx-dashboard-grid{grid-template-columns:minmax(0,1.65fr) minmax(205px,1fr);gap:16px}.nx-dashboard-hero{grid-template-columns:minmax(0,1.5fr) minmax(210px,1fr)}.nx-dashboard-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.nx-dashboard-lower{grid-template-columns:minmax(0,1fr)}.nx-stat-bar{grid-template-columns:repeat(2,minmax(0,1fr))}.nx-stat:nth-child(3){border-top:1px solid var(--nx-line);border-left:0}.nx-stat:nth-child(4){border-top:1px solid var(--nx-line)}.nx-home-grid{grid-template-columns:minmax(0,1fr)}.nx-quick-card{min-height:0}.nx-proxy-top{grid-template-columns:minmax(0,1fr)}.nx-accel-control{grid-template-columns:auto minmax(0,1fr)}.nx-accel-control>.nx-button{grid-column:1/-1;width:100%}.nx-accel-grid,.nx-accel-lower{grid-template-columns:minmax(0,1fr)}.nx-dashboard-main,.nx-dashboard-side{gap:16px}.nx-acceleration{gap:13px;padding:19px 20px}.nx-acceleration-copy h2{font-size:16px}.nx-acceleration-icon{border-radius:13px;flex-basis:44px;width:44px;height:44px}.nx-speed-values{gap:19px}.nx-speed-values strong{font-size:17px}.nx-speed-values small{display:none}.nx-two-columns{grid-template-columns:minmax(0,1.4fr) minmax(205px,1fr);gap:16px}.nx-task-list{padding-block:0}.nx-task-meta{font-size:10px}.nx-total strong{font-size:13px}}@container nx-shell (width<=680px){.nx-dashboard-grid,.nx-two-columns{grid-template-columns:minmax(0,1fr)}.nx-line-meter{display:none}.nx-download-stats{grid-template-columns:minmax(0,1fr)}.nx-download-stats>div+div{border-top:1px solid var(--nx-line);border-left:0}.nx-dashboard-side{grid-template-columns:1fr 1fr;display:grid}.nx-dashboard-side>.nx-modes{grid-column:1/-1}.nx-dashboard-side .nx-mode-options{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;display:grid}.nx-dashboard-side .nx-mode{align-items:flex-start;gap:7px;padding:10px 8px}.nx-dashboard-side .nx-mode>svg{display:none}.nx-dashboard-side .nx-mode-dot{width:12px;height:12px;margin-top:2px}.nx-mode small{font-size:10px}.nx-acceleration-copy p{font-size:11px}.nx-acceleration>.nx-button{padding-inline:12px;font-size:11px}.nx-section-heading{gap:10px}.nx-section-heading p{font-size:11px}.nx-form-grid{grid-template-columns:1fr}.nx-application-actions{grid-template-columns:1fr;gap:22px}.nx-plot{height:160px}.nx-node-list--compact{max-height:190px}}@container nx-shell (width<=520px){.nx-sidebar{flex-basis:59px;width:59px;padding:18px 6px 12px}.nx-brand{padding-bottom:18px}.nx-brand span{display:none}.nx-nav-item{border-radius:9px;gap:4px;min-height:47px}.nx-nav-item span{font-size:10px}.nx-nav-item svg{width:18px;height:18px}.nx-nav-divider{margin-block:11px}.nx-sidebar-foot>span:last-child{display:none}.nx-header{padding:20px 16px 18px}.nx-header h1{font-size:23px}.nx-header p{font-size:11px}.nx-content{padding:0 16px 22px}.nx-notice{margin:0 16px 14px}.nx-header-actions{gap:5px}.nx-live-label{font-size:10px}.nx-live-label>.nx-live-dot{display:none}.nx-acceleration{flex-wrap:wrap;gap:12px;padding:17px}.nx-acceleration-copy{min-width:130px}.nx-acceleration-copy h2{gap:7px}.nx-acceleration>.nx-button{min-height:34px;margin-left:56px}.nx-acceleration-icon{flex-basis:42px;width:42px;height:42px}.nx-panel{padding:16px}.nx-dashboard,.nx-view-stack{gap:16px}.nx-dashboard-side{grid-template-columns:minmax(0,1fr)}.nx-dashboard-side>.nx-modes{grid-column:auto}.nx-dashboard-side .nx-mode-options{display:flex}.nx-dashboard-side .nx-mode>svg{display:block}.nx-dashboard-side .nx-mode{align-items:center}.nx-plot{height:140px}.nx-speed-values{gap:23px}.nx-speed-values strong{font-size:16px}.nx-inline-form{gap:8px}.nx-inline-form>.nx-button{padding-inline:10px;font-size:11px}.nx-inline-form .nx-fit-select{min-width:82px;font-size:11px}.nx-site-shortcuts{gap:1px}.nx-site-shortcuts>span{width:100%;margin-bottom:3px}.nx-download-row{grid-template-columns:28px minmax(0,1fr) auto;gap:10px;padding-block:19px}.nx-file-icon{border-radius:8px;width:28px;height:35px}.nx-file-icon>svg{width:17px}.nx-task-title{flex-direction:column;align-items:flex-start;gap:3px}.nx-task-title>strong{max-width:100%;font-size:12px}.nx-task-title>span{font-size:9px}.nx-task-controls{gap:1px}.nx-task-controls>.nx-icon-button{min-width:27px;padding:4px}.nx-task-meta{gap:4px;font-size:9px}.nx-task-meta>span{width:100%}.nx-task-details{grid-column:1/-1;padding-top:14px}.nx-filter-tabs>button{padding-inline:8px;font-size:11px}.nx-task-list{padding-block:0}.nx-diagnose-start{padding:24px 16px 18px}.nx-diagnose-start>h2{font-size:17px}.nx-diagnose-start>.nx-inline-form{margin-top:18px}.nx-diagnose-options{gap:12px;font-size:10px}.nx-check-row{grid-template-columns:18px minmax(0,1fr) auto 47px;gap:8px}.nx-check-row strong{font-size:11px}.nx-check-row time{font-size:10px}.nx-history-row{gap:9px}.nx-history-row>span:not(.nx-history-result){display:none}.nx-history-row>time{font-size:9px}.nx-section-heading>div{min-width:0}.nx-section-heading h2{font-size:13px}.nx-section-heading>.nx-button{padding-inline:9px;font-size:11px}.nx-schedule-form{flex-wrap:wrap}.nx-schedule-form>.nx-input:first-child{flex-basis:100%}.nx-schedule-row{gap:8px}.nx-schedule-row>.nx-button:not(.nx-icon-button){padding-inline:5px;font-size:10px}.nx-schedule-row strong{font-size:11px}.nx-settings-rows>div{gap:12px}.nx-settings-rows small{font-size:10px}.nx-event{gap:8px;font-size:11px}.nx-event>time{font-size:9px}.nx-rule-row{grid-template-columns:minmax(0,1fr) 96px 24px;gap:5px}.nx-rule-row .nx-input{padding-inline:8px;font-size:11px}.nx-loading-grid{grid-template-columns:1fr}.nx-loading-grid>.nx-skeleton:last-child{display:none}}@media (prefers-reduced-motion:reduce){.nx-app *{scroll-behavior:auto!important;transition:none!important;animation:none!important}}", Np = ".btn{justify-content:center;align-items:center;gap:var(--space-1);font:inherit;white-space:nowrap;cursor:pointer;transition:background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);border:1px solid #0000;display:inline-flex}.btn:disabled{opacity:.45;cursor:default}.btn:not(:disabled):active{transform:translateY(1px)}.btn--secondary,.btn--primary,.btn--quiet{border-radius:12px;min-height:32px;padding:8px 11px;font-size:13px}.btn--primary{background:var(--settings-control-solid,var(--theme-control-solid,#fbf7f0));color:var(--settings-control-text,var(--theme-control-text,#2e3138))}.btn--primary.btn--material{background:var(--settings-control-background,var(--theme-control-background,var(--theme-control-solid,#fbf7f0)));background-image:var(--theme-control-image,none);background-size:var(--theme-control-image-size,auto);background-repeat:var(--theme-control-image-repeat,no-repeat);-webkit-backdrop-filter:var(--theme-control-glass-filter,none);backdrop-filter:var(--theme-control-glass-filter,none);background-position:50%}.btn--primary:hover:not(:disabled){filter:brightness(.94)}.btn--secondary{background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-hover), transparent);color:var(--settings-main-text,var(--theme-main-text,#f2efeb))}.btn--secondary:hover:not(:disabled){background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-active), transparent)}.btn--secondary:active:not(:disabled){background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-press), transparent)}.btn--quiet{color:var(--settings-main-text,var(--theme-main-text,#f2efeb));background:0 0}.btn--quiet:hover:not(:disabled){background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-hover), transparent);color:var(--settings-main-text,var(--theme-main-text,#f2efeb));filter:none}.btn--ghost{border-radius:var(--radius-sm);min-height:32px;color:var(--settings-main-text,var(--theme-main-text,#f2efeb));background:0 0;padding:0 7px;font-size:12px}.btn--ghost:hover:not(:disabled){background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-hover), transparent);color:var(--settings-main-text,var(--theme-main-text,#f2efeb))}.btn--ghost:active:not(:disabled){background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-active), transparent)}.btn--danger{color:color-mix(in srgb, var(--red) 55%, var(--settings-main-text,var(--theme-main-text,#f2efeb)))}.btn--danger:hover:not(:disabled){color:color-mix(in srgb, var(--red) 55%, var(--settings-main-text,var(--theme-main-text,#f2efeb)));background:color-mix(in srgb, var(--settings-main-text,var(--theme-main-text,#f2efeb)) var(--alpha-hover), transparent)}.btn.btn--sm{border-radius:var(--radius-sm);min-height:30px;padding:0 14px;font-size:12px}@media (prefers-reduced-motion:reduce){.btn{transition:none}.btn:not(:disabled):active{transform:none}}", Pp = ".sunday-switch{--sunday-signal:var(--settings-control-solid,var(--theme-control-solid,var(--theme-control-background,#fbf7f0)));--sunday-signal-ink:var(--settings-control-text,var(--theme-control-text,#2e3138));--sunday-area-text:var(--settings-main-text,var(--theme-main-text,#f2efeb));--sunday-w:40px;--sunday-h:24px;--sunday-pad:3px;--sunday-thumb:16px;--sunday-travel:calc(var(--sunday-w) - 2px - (var(--sunday-pad) * 2) - var(--sunday-thumb));cursor:pointer;flex:none;align-items:center;display:inline-flex;position:relative}.sunday-switch--sm{--sunday-w:34px;--sunday-h:20px;--sunday-pad:2px;--sunday-thumb:14px;--sunday-travel:calc(var(--sunday-w) - 2px - (var(--sunday-pad) * 2) - var(--sunday-thumb))}.sunday-switch__input{z-index:2;opacity:0;cursor:pointer;width:100%;height:100%;margin:0;position:absolute;inset:0}.sunday-switch__input:disabled{cursor:not-allowed}.sunday-switch__track{width:var(--sunday-w);height:var(--sunday-h);border:1px solid color-mix(in srgb, var(--sunday-area-text) 18%, transparent);border-radius:var(--radius-sm);background:color-mix(in srgb, var(--sunday-area-text) 6%, transparent);transition:background-color var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out);flex:none;position:relative}.sunday-switch__thumb{top:var(--sunday-pad);left:var(--sunday-pad);width:var(--sunday-thumb);height:var(--sunday-thumb);border-radius:calc(var(--radius-sm) / 2);background:color-mix(in srgb, var(--sunday-area-text) 46%, transparent);transition:transform var(--dur-slow) var(--ease-out), background-color var(--dur-base) var(--ease-out);position:absolute}.sunday-switch:hover .sunday-switch__track{border-color:color-mix(in srgb, var(--sunday-area-text) 32%, transparent)}.sunday-switch:hover .sunday-switch__thumb{background:color-mix(in srgb, var(--sunday-area-text) 62%, transparent)}.sunday-switch__input:checked+.sunday-switch__track{border-color:var(--sunday-signal);background:var(--sunday-signal)}.sunday-switch__input:checked+.sunday-switch__track .sunday-switch__thumb{background:var(--sunday-signal-ink);transform:translateX(var(--sunday-travel))}.sunday-switch:hover .sunday-switch__input:checked+.sunday-switch__track{border-color:color-mix(in srgb, var(--sunday-signal) 92%, var(--sunday-signal-ink));background:color-mix(in srgb, var(--sunday-signal) 92%, var(--sunday-signal-ink))}.sunday-switch__input:focus-visible+.sunday-switch__track{outline:2px solid var(--blue);outline-offset:2px}.sunday-switch:has(.sunday-switch__input:disabled){cursor:not-allowed}.sunday-switch__input:disabled+.sunday-switch__track{border-color:color-mix(in srgb, var(--sunday-area-text) 10%, transparent);background:color-mix(in srgb, var(--sunday-area-text) 4%, transparent)}.sunday-switch__input:disabled+.sunday-switch__track .sunday-switch__thumb{background:color-mix(in srgb, var(--sunday-area-text) 24%, transparent)}.sunday-switch__input:disabled:checked+.sunday-switch__track{border-color:color-mix(in srgb, var(--sunday-area-text) 12%, transparent);background:color-mix(in srgb, var(--sunday-area-text) 12%, transparent)}.sunday-switch__input:disabled:checked+.sunday-switch__track .sunday-switch__thumb{background:color-mix(in srgb, var(--sunday-area-text) 44%, transparent);transform:translateX(var(--sunday-travel))}.sunday-switch__label{color:inherit;font-size:inherit;white-space:nowrap;margin-inline-start:var(--space-2);line-height:1.3}@media (prefers-reduced-motion:reduce){.sunday-switch__track,.sunday-switch__thumb{transition:none}}", Fp = ".ui-select{--ui-select-arrow-inset:11px;--ui-select-arrow-size:7px;--ui-select-arrow-gap:var(--space-1);min-width:0;position:relative}.ui-select-trigger{border:1px solid color-mix(in srgb, var(--settings-control-text,var(--theme-control-text,#f4f1ec)) 12%, transparent);border-radius:var(--radius-sm);background:color-mix(in srgb, var(--settings-control-solid,var(--theme-control-solid,#242424)) 70%, transparent);width:100%;min-height:32px;color:var(--settings-control-text,var(--theme-control-text,#f4f1ec));padding:0 calc(var(--ui-select-arrow-inset) + var(--ui-select-arrow-size) + var(--ui-select-arrow-gap)) 0 var(--space-2);text-align:left;align-items:center;font-size:13px;display:inline-flex}.ui-select-trigger:disabled{opacity:.45;cursor:default}.ui-select-trigger span:first-child{white-space:nowrap;text-overflow:ellipsis;min-width:0;overflow:hidden}.ui-select-arrow{right:var(--ui-select-arrow-inset);width:var(--ui-select-arrow-size);height:var(--ui-select-arrow-size);opacity:.7;transition:transform var(--dur-fast) var(--ease-out);border-bottom:1.5px solid;border-right:1.5px solid;position:absolute;top:50%;transform:translateY(-65%)rotate(45deg)}.ui-select.open .ui-select-arrow{transform:translateY(-35%)rotate(225deg)}.ui-select-menu{z-index:var(--ui-select-layer,var(--z-popover,60));border:1px solid color-mix(in srgb, currentColor 12%, transparent);border-radius:var(--radius);background:var(--settings-control-solid,var(--theme-control-background,#242424));max-height:320px;color:var(--settings-control-text,var(--theme-control-text,#f4f1ec));box-shadow:var(--shadow-md);animation:popover-in var(--dur-base) var(--ease-out);transform-origin:top;gap:4px;padding:6px;display:grid;position:fixed;top:0;left:0;overflow:auto}.ui-select-menu--up{transform-origin:bottom}.ui-select-group{gap:2px;display:grid}.ui-select-group+.ui-select-group{border-top:1px solid color-mix(in srgb, currentColor 12%, transparent);margin-top:6px;padding-top:6px}.ui-select-group-label{color:color-mix(in srgb, currentColor 72%, transparent);white-space:nowrap;text-overflow:ellipsis;padding:4px 9px 3px;font-size:12px;font-weight:700;line-height:1.35;overflow:hidden}.ui-select-option{min-height:30px;color:inherit;text-align:left;white-space:nowrap;text-overflow:ellipsis;background:0 0;border:0;border-radius:0;padding:5px 9px;font-size:13px;line-height:1.35;display:block;position:relative;overflow:hidden}.ui-select-option:before{content:\"\";pointer-events:none;-webkit-mask-image:linear-gradient(to right, #0003 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), #0003 100%);-webkit-mask-image:linear-gradient(to right, #0003 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), #0003 100%);mask-image:linear-gradient(to right, #0003 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), #0003 100%);background:0 0;border-radius:0;position:absolute;inset:0}.ui-select-option:hover:before,.ui-select-option:focus-visible:before{background:color-mix(in srgb, currentColor var(--alpha-hover), transparent)}.ui-select-option:focus-visible{outline:none}.ui-select-option.active:before{background:color-mix(in srgb, currentColor var(--alpha-active), transparent)}.ui-select-option.active.active-accent{color:var(--green,#32d17d);background:0 0}.ui-select-option.separator-before{margin-top:7px;position:relative}.ui-select-option.separator-before:after{content:\"\";background:color-mix(in srgb, currentColor 16%, transparent);height:1px;position:absolute;top:-4px;left:9px;right:9px}.ui-select-option.disabled{opacity:.45;cursor:default}@media (prefers-reduced-motion:reduce){.ui-select-arrow{transition:none}.ui-select-menu{animation:none}}";
//#endregion
//#region ../src/lamtools_core/plugins/bundled/network-exploration/ui/src/page.mjs
function Ip(e, t) {
	if (t.addStyle) return t.addStyle(`${Np}\n${Mp}\n${Pp}\n${Fp}`);
	let n = e.ownerDocument, r = n.createElement("style");
	return r.nonce = n.querySelector("style[nonce]")?.nonce || "", r.dataset.networkPluginStyle = "true", r.textContent = `${Np}\n${Mp}\n${Pp}\n${Fp}`, n.head.append(r), () => r.remove();
}
function Lp(e, t) {
	return zp(e, t, vp);
}
function Rp(e, t) {
	return zp(e, t, jp);
}
function zp(e, t, n) {
	let r = Ip(e, t), i = !1, a = document.createElement("div");
	a.className = n === jp ? "nx-mount nx-mount--quick" : "nx-mount", e.append(a), Bp++;
	let o = e.closest(".split-plugin-page");
	o?.classList.add("nx-host");
	let s = e.closest(".workspace-main");
	s?.classList.add("nx-plugin-full");
	let c = Es(n, { context: t });
	c.config.idPrefix = `network-${Bp}`;
	let l = () => {
		i || (i = !0, t.signal?.removeEventListener("abort", l), c.unmount(), r(), a.remove(), o?.classList.remove("nx-host"), s?.classList.remove("nx-plugin-full"));
	};
	try {
		c.mount(a);
	} catch (e) {
		throw l(), e;
	}
	return t.signal?.addEventListener("abort", l, { once: !0 }), l;
}
var Bp = 0;
//#endregion
export { Lp as mount, Rp as mountQuick };
