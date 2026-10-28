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
}, d = Object.prototype.hasOwnProperty, f = (e, t) => d.call(e, t), p = Array.isArray, m = (e) => C(e) === "[object Map]", h = (e) => C(e) === "[object Set]", g = (e) => C(e) === "[object Date]", _ = (e) => typeof e == "function", v = (e) => typeof e == "string", y = (e) => typeof e == "symbol", b = (e) => typeof e == "object" && !!e, x = (e) => (b(e) || _(e)) && _(e.then) && _(e.catch), S = Object.prototype.toString, C = (e) => S.call(e), w = (e) => C(e).slice(8, -1), T = (e) => C(e) === "[object Object]", ee = (e) => v(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, te = /* @__PURE__ */ n(",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"), ne = (e) => {
	let t = /* @__PURE__ */ Object.create(null);
	return ((n) => t[n] || (t[n] = e(n)));
}, re = /-\w/g, E = ne((e) => e.replace(re, (e) => e.slice(1).toUpperCase())), ie = /\B([A-Z])/g, ae = ne((e) => e.replace(ie, "-$1").toLowerCase()), oe = ne((e) => e.charAt(0).toUpperCase() + e.slice(1)), se = ne((e) => e ? `on${oe(e)}` : ""), D = (e, t) => !Object.is(e, t), ce = (e, ...t) => {
	for (let n = 0; n < e.length; n++) e[n](...t);
}, le = (e, t, n, r = !1) => {
	Object.defineProperty(e, t, {
		configurable: !0,
		enumerable: !1,
		writable: r,
		value: n
	});
}, ue = (e) => {
	let t = parseFloat(e);
	return isNaN(t) ? e : t;
}, de = (e) => {
	let t = v(e) ? Number(e) : NaN;
	return isNaN(t) ? e : t;
}, fe, pe = () => fe ||= typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {};
function me(e) {
	if (p(e)) {
		let t = {};
		for (let n = 0; n < e.length; n++) {
			let r = e[n], i = v(r) ? ve(r) : me(r);
			if (i) for (let e in i) t[e] = i[e];
		}
		return t;
	} else if (v(e) || b(e)) return e;
}
var he = /;(?![^(]*\))/g, ge = /:([^]+)/, _e = /\/\*[^]*?\*\//g;
function ve(e) {
	let t = {};
	return e.replace(_e, "").split(he).forEach((e) => {
		if (e) {
			let n = e.split(ge);
			n.length > 1 && (t[n[0].trim()] = n[1].trim());
		}
	}), t;
}
function O(e) {
	let t = "";
	if (v(e)) t = e;
	else if (p(e)) for (let n = 0; n < e.length; n++) {
		let r = O(e[n]);
		r && (t += r + " ");
	}
	else if (b(e)) for (let n in e) e[n] && (t += n + " ");
	return t.trim();
}
var ye = "itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,readonly", be = /* @__PURE__ */ n(ye);
ye + "";
function xe(e) {
	return !!e || e === "";
}
function Se(e, t) {
	if (e.length !== t.length) return !1;
	let n = !0;
	for (let r = 0; n && r < e.length; r++) n = Ce(e[r], t[r]);
	return n;
}
function Ce(e, t) {
	if (e === t) return !0;
	let n = g(e), r = g(t);
	if (n || r) return n && r ? e.getTime() === t.getTime() : !1;
	if (n = y(e), r = y(t), n || r) return e === t;
	if (n = p(e), r = p(t), n || r) return n && r ? Se(e, t) : !1;
	if (n = b(e), r = b(t), n || r) {
		if (!n || !r || Object.keys(e).length !== Object.keys(t).length) return !1;
		for (let n in e) {
			let r = e.hasOwnProperty(n), i = t.hasOwnProperty(n);
			if (r && !i || !r && i || !Ce(e[n], t[n])) return !1;
		}
	}
	return String(e) === String(t);
}
function we(e, t) {
	return e.findIndex((e) => Ce(e, t));
}
var Te = (e) => !!(e && e.__v_isRef === !0), k = (e) => v(e) ? e : e == null ? "" : p(e) || b(e) && (e.toString === S || !_(e.toString)) ? Te(e) ? k(e.value) : JSON.stringify(e, Ee, 2) : String(e), Ee = (e, t) => Te(t) ? Ee(e, t.value) : m(t) ? { [`Map(${t.size})`]: [...t.entries()].reduce((e, [t, n], r) => (e[De(t, r) + " =>"] = n, e), {}) } : h(t) ? { [`Set(${t.size})`]: [...t.values()].map((e) => De(e)) } : y(t) ? De(t) : b(t) && !p(t) && !T(t) ? String(t) : t, De = (e, t = "") => y(e) ? `Symbol(${e.description ?? t})` : e, A, Oe = class {
	constructor(e = !1) {
		this.detached = e, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !e && A && (A.active ? (this.parent = A, this.index = (A.scopes ||= []).push(this) - 1) : (this._active = !1, this._warnOnRun = !1));
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
			let t = A;
			try {
				return A = this, e();
			} finally {
				A = t;
			}
		}
	}
	on() {
		++this._on === 1 && (this.prevScope = A, A = this);
	}
	off() {
		if (this._on > 0 && --this._on === 0) {
			if (A === this) A = this.prevScope;
			else {
				let e = A;
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
function ke() {
	return A;
}
var j, Ae = /* @__PURE__ */ new WeakSet(), je = class {
	constructor(e) {
		this.fn = e, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, A && (A.active ? A.effects.push(this) : this.flags &= -2);
	}
	pause() {
		this.flags |= 64;
	}
	resume() {
		this.flags & 64 && (this.flags &= -65, Ae.has(this) && (Ae.delete(this), this.trigger()));
	}
	notify() {
		this.flags & 2 && !(this.flags & 32) || this.flags & 8 || Fe(this);
	}
	run() {
		if (!(this.flags & 1)) return this.fn();
		this.flags |= 2, Je(this), Re(this);
		let e = j, t = We;
		j = this, We = !0;
		try {
			return this.fn();
		} finally {
			ze(this), j = e, We = t, this.flags &= -3;
		}
	}
	stop() {
		if (this.flags & 1) {
			for (let e = this.deps; e; e = e.nextDep) He(e);
			this.deps = this.depsTail = void 0, Je(this), this.onStop && this.onStop(), this.flags &= -2;
		}
	}
	trigger() {
		this.flags & 64 ? Ae.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
	}
	runIfDirty() {
		Be(this) && this.run();
	}
	get dirty() {
		return Be(this);
	}
}, Me = 0, Ne, Pe;
function Fe(e, t = !1) {
	if (e.flags |= 8, t) {
		e.next = Pe, Pe = e;
		return;
	}
	e.next = Ne, Ne = e;
}
function Ie() {
	Me++;
}
function Le() {
	if (--Me > 0) return;
	if (Pe) {
		let e = Pe;
		for (Pe = void 0; e;) {
			let t = e.next;
			e.next = void 0, e.flags &= -9, e = t;
		}
	}
	let e;
	for (; Ne;) {
		let t = Ne;
		for (Ne = void 0; t;) {
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
function Re(e) {
	for (let t = e.deps; t; t = t.nextDep) t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function ze(e) {
	let t, n = e.depsTail, r = n;
	for (; r;) {
		let e = r.prevDep;
		r.version === -1 ? (r === n && (n = e), He(r), Ue(r)) : t = r, r.dep.activeLink = r.prevActiveLink, r.prevActiveLink = void 0, r = e;
	}
	e.deps = t, e.depsTail = n;
}
function Be(e) {
	for (let t = e.deps; t; t = t.nextDep) if (t.dep.version !== t.version || t.dep.computed && (Ve(t.dep.computed) || t.dep.version !== t.version)) return !0;
	return !!e._dirty;
}
function Ve(e) {
	if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === Ye) || (e.globalVersion = Ye, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !Be(e)))) return;
	e.flags |= 2;
	let t = e.dep, n = j, r = We;
	j = e, We = !0;
	try {
		Re(e);
		let n = e.fn(e._value);
		(t.version === 0 || D(n, e._value)) && (e.flags |= 128, e._value = n, t.version++);
	} catch (e) {
		throw t.version++, e;
	} finally {
		j = n, We = r, ze(e), e.flags &= -3;
	}
}
function He(e, t = !1) {
	let { dep: n, prevSub: r, nextSub: i } = e;
	if (r && (r.nextSub = i, e.prevSub = void 0), i && (i.prevSub = r, e.nextSub = void 0), n.subs === e && (n.subs = r, !r && n.computed)) {
		n.computed.flags &= -5;
		for (let e = n.computed.deps; e; e = e.nextDep) He(e, !0);
	}
	!t && !--n.sc && n.map && n.map.delete(n.key);
}
function Ue(e) {
	let { prevDep: t, nextDep: n } = e;
	t && (t.nextDep = n, e.prevDep = void 0), n && (n.prevDep = t, e.nextDep = void 0);
}
var We = !0, Ge = [];
function Ke() {
	Ge.push(We), We = !1;
}
function qe() {
	let e = Ge.pop();
	We = e === void 0 ? !0 : e;
}
function Je(e) {
	let { cleanup: t } = e;
	if (e.cleanup = void 0, t) {
		let e = j;
		j = void 0;
		try {
			t();
		} finally {
			j = e;
		}
	}
}
var Ye = 0, Xe = class {
	constructor(e, t) {
		this.sub = e, this.dep = t, this.version = t.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
	}
}, Ze = class {
	constructor(e) {
		this.computed = e, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
	}
	track(e) {
		if (!j || !We || j === this.computed) return;
		let t = this.activeLink;
		if (t === void 0 || t.sub !== j) t = this.activeLink = new Xe(j, this), j.deps ? (t.prevDep = j.depsTail, j.depsTail.nextDep = t, j.depsTail = t) : j.deps = j.depsTail = t, Qe(t);
		else if (t.version === -1 && (t.version = this.version, t.nextDep)) {
			let e = t.nextDep;
			e.prevDep = t.prevDep, t.prevDep && (t.prevDep.nextDep = e), t.prevDep = j.depsTail, t.nextDep = void 0, j.depsTail.nextDep = t, j.depsTail = t, j.deps === t && (j.deps = e);
		}
		return t;
	}
	trigger(e) {
		this.version++, Ye++, this.notify(e);
	}
	notify(e) {
		Ie();
		try {
			for (let e = this.subs; e; e = e.prevSub) e.sub.notify() && e.sub.dep.notify();
		} finally {
			Le();
		}
	}
};
function Qe(e) {
	if (e.dep.sc++, e.sub.flags & 4) {
		let t = e.dep.computed;
		if (t && !e.dep.subs) {
			t.flags |= 20;
			for (let e = t.deps; e; e = e.nextDep) Qe(e);
		}
		let n = e.dep.subs;
		n !== e && (e.prevSub = n, n && (n.nextSub = e)), e.dep.subs = e;
	}
}
var $e = /* @__PURE__ */ new WeakMap(), et = /* @__PURE__ */ Symbol(""), tt = /* @__PURE__ */ Symbol(""), nt = /* @__PURE__ */ Symbol("");
function M(e, t, n) {
	if (We && j) {
		let t = $e.get(e);
		t || $e.set(e, t = /* @__PURE__ */ new Map());
		let r = t.get(n);
		r || (t.set(n, r = new Ze()), r.map = t, r.key = n), r.track();
	}
}
function rt(e, t, n, r, i, a) {
	let o = $e.get(e);
	if (!o) {
		Ye++;
		return;
	}
	let s = (e) => {
		e && e.trigger();
	};
	if (Ie(), t === "clear") o.forEach(s);
	else {
		let i = p(e), a = i && ee(n);
		if (i && n === "length") {
			let e = Number(r);
			o.forEach((t, n) => {
				(n === "length" || n === nt || !y(n) && n >= e) && s(t);
			});
		} else switch ((n !== void 0 || o.has(void 0)) && s(o.get(n)), a && s(o.get(nt)), t) {
			case "add":
				i ? a && s(o.get("length")) : (s(o.get(et)), m(e) && s(o.get(tt)));
				break;
			case "delete":
				i || (s(o.get(et)), m(e) && s(o.get(tt)));
				break;
			case "set":
				m(e) && s(o.get(et));
				break;
		}
	}
	Le();
}
function it(e) {
	let t = /* @__PURE__ */ N(e);
	return t === e ? t : (M(t, "iterate", nt), /* @__PURE__ */ Ut(e) ? t : t.map(Kt));
}
function at(e) {
	return M(e = /* @__PURE__ */ N(e), "iterate", nt), e;
}
function ot(e, t) {
	return /* @__PURE__ */ Ht(e) ? qt(/* @__PURE__ */ Vt(e) ? Kt(t) : t) : Kt(t);
}
var st = {
	__proto__: null,
	[Symbol.iterator]() {
		return ct(this, Symbol.iterator, (e) => ot(this, e));
	},
	concat(...e) {
		return it(this).concat(...e.map((e) => p(e) ? it(e) : e));
	},
	entries() {
		return ct(this, "entries", (e) => (e[1] = ot(this, e[1]), e));
	},
	every(e, t) {
		return ut(this, "every", e, t, void 0, arguments);
	},
	filter(e, t) {
		return ut(this, "filter", e, t, (e) => e.map((e) => ot(this, e)), arguments);
	},
	find(e, t) {
		return ut(this, "find", e, t, (e) => ot(this, e), arguments);
	},
	findIndex(e, t) {
		return ut(this, "findIndex", e, t, void 0, arguments);
	},
	findLast(e, t) {
		return ut(this, "findLast", e, t, (e) => ot(this, e), arguments);
	},
	findLastIndex(e, t) {
		return ut(this, "findLastIndex", e, t, void 0, arguments);
	},
	forEach(e, t) {
		return ut(this, "forEach", e, t, void 0, arguments);
	},
	includes(...e) {
		return ft(this, "includes", e);
	},
	indexOf(...e) {
		return ft(this, "indexOf", e);
	},
	join(e) {
		return it(this).join(e);
	},
	lastIndexOf(...e) {
		return ft(this, "lastIndexOf", e);
	},
	map(e, t) {
		return ut(this, "map", e, t, void 0, arguments);
	},
	pop() {
		return pt(this, "pop");
	},
	push(...e) {
		return pt(this, "push", e);
	},
	reduce(e, ...t) {
		return dt(this, "reduce", e, t);
	},
	reduceRight(e, ...t) {
		return dt(this, "reduceRight", e, t);
	},
	shift() {
		return pt(this, "shift");
	},
	some(e, t) {
		return ut(this, "some", e, t, void 0, arguments);
	},
	splice(...e) {
		return pt(this, "splice", e);
	},
	toReversed() {
		return it(this).toReversed();
	},
	toSorted(e) {
		return it(this).toSorted(e);
	},
	toSpliced(...e) {
		return it(this).toSpliced(...e);
	},
	unshift(...e) {
		return pt(this, "unshift", e);
	},
	values() {
		return ct(this, "values", (e) => ot(this, e));
	}
};
function ct(e, t, n) {
	let r = at(e), i = r[t]();
	return r !== e && !/* @__PURE__ */ Ut(e) && (i._next = i.next, i.next = () => {
		let e = i._next();
		return e.done || (e.value = n(e.value)), e;
	}), i;
}
var lt = Array.prototype;
function ut(e, t, n, r, i, a) {
	let o = at(e), s = o !== e && !/* @__PURE__ */ Ut(e), c = o[t];
	if (c !== lt[t]) {
		let t = c.apply(e, a);
		return s ? Kt(t) : t;
	}
	let l = n;
	o !== e && (s ? l = function(t, r) {
		return n.call(this, ot(e, t), r, e);
	} : n.length > 2 && (l = function(t, r) {
		return n.call(this, t, r, e);
	}));
	let u = c.call(o, l, r);
	return s && i ? i(u) : u;
}
function dt(e, t, n, r) {
	let i = at(e), a = i !== e && !/* @__PURE__ */ Ut(e), o = n, s = !1;
	i !== e && (a ? (s = r.length === 0, o = function(t, r, i) {
		return s && (s = !1, t = ot(e, t)), n.call(this, t, ot(e, r), i, e);
	}) : n.length > 3 && (o = function(t, r, i) {
		return n.call(this, t, r, i, e);
	}));
	let c = i[t](o, ...r);
	return s ? ot(e, c) : c;
}
function ft(e, t, n) {
	let r = /* @__PURE__ */ N(e);
	M(r, "iterate", nt);
	let i = r[t](...n);
	return (i === -1 || i === !1) && /* @__PURE__ */ Wt(n[0]) ? (n[0] = /* @__PURE__ */ N(n[0]), r[t](...n)) : i;
}
function pt(e, t, n = []) {
	Ke(), Ie();
	let r = (/* @__PURE__ */ N(e))[t].apply(e, n);
	return Le(), qe(), r;
}
var mt = /* @__PURE__ */ n("__proto__,__v_isRef,__isVue"), ht = new Set(/* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(y));
function gt(e) {
	y(e) || (e = String(e));
	let t = /* @__PURE__ */ N(this);
	return M(t, "has", e), t.hasOwnProperty(e);
}
var _t = class {
	constructor(e = !1, t = !1) {
		this._isReadonly = e, this._isShallow = t;
	}
	get(e, t, n) {
		if (t === "__v_skip") return e.__v_skip;
		let r = this._isReadonly, i = this._isShallow;
		if (t === "__v_isReactive") return !r;
		if (t === "__v_isReadonly") return r;
		if (t === "__v_isShallow") return i;
		if (t === "__v_raw") return n === (r ? i ? Ft : Pt : i ? Nt : Mt).get(e) || Object.getPrototypeOf(e) === Object.getPrototypeOf(n) ? e : void 0;
		let a = p(e);
		if (!r) {
			let e;
			if (a && (e = st[t])) return e;
			if (t === "hasOwnProperty") return gt;
		}
		let o = Reflect.get(e, t, /* @__PURE__ */ P(e) ? e : n);
		if ((y(t) ? ht.has(t) : mt(t)) || (r || M(e, "get", t), i)) return o;
		if (/* @__PURE__ */ P(o)) {
			let e = a && ee(t) ? o : o.value;
			return r && b(e) ? /* @__PURE__ */ zt(e) : e;
		}
		return b(o) ? r ? /* @__PURE__ */ zt(o) : /* @__PURE__ */ Lt(o) : o;
	}
}, vt = class extends _t {
	constructor(e = !1) {
		super(!1, e);
	}
	set(e, t, n, r) {
		let i = e[t], a = p(e) && ee(t);
		if (!this._isShallow) {
			let e = /* @__PURE__ */ Ht(i);
			if (!/* @__PURE__ */ Ut(n) && !/* @__PURE__ */ Ht(n) && (i = /* @__PURE__ */ N(i), n = /* @__PURE__ */ N(n)), !a && /* @__PURE__ */ P(i) && !/* @__PURE__ */ P(n)) return e || (i.value = n), !0;
		}
		let o = a ? Number(t) < e.length : f(e, t), s = Reflect.set(e, t, n, /* @__PURE__ */ P(e) ? e : r);
		return e === /* @__PURE__ */ N(r) && (o ? D(n, i) && rt(e, "set", t, n, i) : rt(e, "add", t, n)), s;
	}
	deleteProperty(e, t) {
		let n = f(e, t), r = e[t], i = Reflect.deleteProperty(e, t);
		return i && n && rt(e, "delete", t, void 0, r), i;
	}
	has(e, t) {
		let n = Reflect.has(e, t);
		return (!y(t) || !ht.has(t)) && M(e, "has", t), n;
	}
	ownKeys(e) {
		return M(e, "iterate", p(e) ? "length" : et), Reflect.ownKeys(e);
	}
}, yt = class extends _t {
	constructor(e = !1) {
		super(!0, e);
	}
	set(e, t) {
		return !0;
	}
	deleteProperty(e, t) {
		return !0;
	}
}, bt = /* @__PURE__ */ new vt(), xt = /* @__PURE__ */ new yt(), St = /* @__PURE__ */ new vt(!0), Ct = (e) => e, wt = (e) => Reflect.getPrototypeOf(e);
function Tt(e, t, n) {
	return function(...r) {
		let i = this.__v_raw, a = /* @__PURE__ */ N(i), o = m(a), s = e === "entries" || e === Symbol.iterator && o, c = e === "keys" && o, u = i[e](...r), d = n ? Ct : t ? qt : Kt;
		return !t && M(a, "iterate", c ? tt : et), l(Object.create(u), { next() {
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
function Et(e) {
	return function(...t) {
		return e === "delete" ? !1 : e === "clear" ? void 0 : this;
	};
}
function Dt(e, t) {
	let n = {
		get(n) {
			let r = this.__v_raw, i = /* @__PURE__ */ N(r), a = /* @__PURE__ */ N(n);
			e || (D(n, a) && M(i, "get", n), M(i, "get", a));
			let { has: o } = wt(i), s = t ? Ct : e ? qt : Kt;
			if (o.call(i, n)) return s(r.get(n));
			if (o.call(i, a)) return s(r.get(a));
			r !== i && r.get(n);
		},
		get size() {
			let t = this.__v_raw;
			return !e && M(/* @__PURE__ */ N(t), "iterate", et), t.size;
		},
		has(t) {
			let n = this.__v_raw, r = /* @__PURE__ */ N(n), i = /* @__PURE__ */ N(t);
			return e || (D(t, i) && M(r, "has", t), M(r, "has", i)), t === i ? n.has(t) : n.has(t) || n.has(i);
		},
		forEach(n, r) {
			let i = this, a = i.__v_raw, o = /* @__PURE__ */ N(a), s = t ? Ct : e ? qt : Kt;
			return !e && M(o, "iterate", et), a.forEach((e, t) => n.call(r, s(e), s(t), i));
		}
	};
	return l(n, e ? {
		add: Et("add"),
		set: Et("set"),
		delete: Et("delete"),
		clear: Et("clear")
	} : {
		add(e) {
			let n = /* @__PURE__ */ N(this), r = wt(n), i = /* @__PURE__ */ N(e), a = !t && !/* @__PURE__ */ Ut(e) && !/* @__PURE__ */ Ht(e) ? i : e;
			return r.has.call(n, a) || D(e, a) && r.has.call(n, e) || D(i, a) && r.has.call(n, i) || (n.add(a), rt(n, "add", a, a)), this;
		},
		set(e, n) {
			!t && !/* @__PURE__ */ Ut(n) && !/* @__PURE__ */ Ht(n) && (n = /* @__PURE__ */ N(n));
			let r = /* @__PURE__ */ N(this), { has: i, get: a } = wt(r), o = i.call(r, e);
			o ||= (e = /* @__PURE__ */ N(e), i.call(r, e));
			let s = a.call(r, e);
			return r.set(e, n), o ? D(n, s) && rt(r, "set", e, n, s) : rt(r, "add", e, n), this;
		},
		delete(e) {
			let t = /* @__PURE__ */ N(this), { has: n, get: r } = wt(t), i = n.call(t, e);
			i ||= (e = /* @__PURE__ */ N(e), n.call(t, e));
			let a = r ? r.call(t, e) : void 0, o = t.delete(e);
			return i && rt(t, "delete", e, void 0, a), o;
		},
		clear() {
			let e = /* @__PURE__ */ N(this), t = e.size !== 0, n = e.clear();
			return t && rt(e, "clear", void 0, void 0, void 0), n;
		}
	}), [
		"keys",
		"values",
		"entries",
		Symbol.iterator
	].forEach((r) => {
		n[r] = Tt(r, e, t);
	}), n;
}
function Ot(e, t) {
	let n = Dt(e, t);
	return (t, r, i) => r === "__v_isReactive" ? !e : r === "__v_isReadonly" ? e : r === "__v_raw" ? t : Reflect.get(f(n, r) && r in t ? n : t, r, i);
}
var kt = { get: /* @__PURE__ */ Ot(!1, !1) }, At = { get: /* @__PURE__ */ Ot(!1, !0) }, jt = { get: /* @__PURE__ */ Ot(!0, !1) }, Mt = /* @__PURE__ */ new WeakMap(), Nt = /* @__PURE__ */ new WeakMap(), Pt = /* @__PURE__ */ new WeakMap(), Ft = /* @__PURE__ */ new WeakMap();
function It(e) {
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
function Lt(e) {
	return /* @__PURE__ */ Ht(e) ? e : Bt(e, !1, bt, kt, Mt);
}
// @__NO_SIDE_EFFECTS__
function Rt(e) {
	return Bt(e, !1, St, At, Nt);
}
// @__NO_SIDE_EFFECTS__
function zt(e) {
	return Bt(e, !0, xt, jt, Pt);
}
function Bt(e, t, n, r, i) {
	if (!b(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e)) return e;
	let a = i.get(e);
	if (a) return a;
	let o = It(w(e));
	if (o === 0) return e;
	let s = new Proxy(e, o === 2 ? r : n);
	return i.set(e, s), s;
}
// @__NO_SIDE_EFFECTS__
function Vt(e) {
	return /* @__PURE__ */ Ht(e) ? /* @__PURE__ */ Vt(e.__v_raw) : !!(e && e.__v_isReactive);
}
// @__NO_SIDE_EFFECTS__
function Ht(e) {
	return !!(e && e.__v_isReadonly);
}
// @__NO_SIDE_EFFECTS__
function Ut(e) {
	return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function Wt(e) {
	return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function N(e) {
	let t = e && e.__v_raw;
	return t ? /* @__PURE__ */ N(t) : e;
}
function Gt(e) {
	return !f(e, "__v_skip") && Object.isExtensible(e) && le(e, "__v_skip", !0), e;
}
var Kt = (e) => b(e) ? /* @__PURE__ */ Lt(e) : e, qt = (e) => b(e) ? /* @__PURE__ */ zt(e) : e;
// @__NO_SIDE_EFFECTS__
function P(e) {
	return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function F(e) {
	return Yt(e, !1);
}
// @__NO_SIDE_EFFECTS__
function Jt(e) {
	return Yt(e, !0);
}
function Yt(e, t) {
	return /* @__PURE__ */ P(e) ? e : new Xt(e, t);
}
var Xt = class {
	constructor(e, t) {
		this.dep = new Ze(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = t ? e : /* @__PURE__ */ N(e), this._value = t ? e : Kt(e), this.__v_isShallow = t;
	}
	get value() {
		return this.dep.track(), this._value;
	}
	set value(e) {
		let t = this._rawValue, n = this.__v_isShallow || /* @__PURE__ */ Ut(e) || /* @__PURE__ */ Ht(e);
		e = n ? e : /* @__PURE__ */ N(e), D(e, t) && (this._rawValue = e, this._value = n ? e : Kt(e), this.dep.trigger());
	}
};
function I(e) {
	return /* @__PURE__ */ P(e) ? e.value : e;
}
var Zt = {
	get: (e, t, n) => t === "__v_raw" ? e : I(Reflect.get(e, t, n)),
	set: (e, t, n, r) => {
		let i = e[t];
		return /* @__PURE__ */ P(i) && !/* @__PURE__ */ P(n) ? (i.value = n, !0) : Reflect.set(e, t, n, r);
	}
};
function Qt(e) {
	return /* @__PURE__ */ Vt(e) ? e : new Proxy(e, Zt);
}
var $t = class {
	constructor(e, t, n) {
		this.fn = e, this.setter = t, this._value = void 0, this.dep = new Ze(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = Ye - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !t, this.isSSR = n;
	}
	notify() {
		if (this.flags |= 16, !(this.flags & 8) && j !== this) return Fe(this, !0), !0;
	}
	get value() {
		let e = this.dep.track();
		return Ve(this), e && (e.version = this.dep.version), this._value;
	}
	set value(e) {
		this.setter && this.setter(e);
	}
};
// @__NO_SIDE_EFFECTS__
function en(e, t, n = !1) {
	let r, i;
	return _(e) ? r = e : (r = e.get, i = e.set), new $t(r, i, n);
}
var tn = {}, nn = /* @__PURE__ */ new WeakMap(), rn = void 0;
function an(e, t = !1, n = rn) {
	if (n) {
		let t = nn.get(n);
		t || nn.set(n, t = []), t.push(e);
	}
}
function on(e, t, n = r) {
	let { immediate: i, deep: o, once: s, scheduler: c, augmentJob: l, call: d } = n, f = (e) => o ? e : /* @__PURE__ */ Ut(e) || o === !1 || o === 0 ? sn(e, 1) : sn(e), m, h, g, v, y = !1, b = !1;
	if (/* @__PURE__ */ P(e) ? (h = () => e.value, y = /* @__PURE__ */ Ut(e)) : /* @__PURE__ */ Vt(e) ? (h = () => f(e), y = !0) : p(e) ? (b = !0, y = e.some((e) => /* @__PURE__ */ Vt(e) || /* @__PURE__ */ Ut(e)), h = () => e.map((e) => {
		if (/* @__PURE__ */ P(e)) return e.value;
		if (/* @__PURE__ */ Vt(e)) return f(e);
		if (_(e)) return d ? d(e, 2) : e();
	})) : h = _(e) ? t ? d ? () => d(e, 2) : e : () => {
		if (g) {
			Ke();
			try {
				g();
			} finally {
				qe();
			}
		}
		let t = rn;
		rn = m;
		try {
			return d ? d(e, 3, [v]) : e(v);
		} finally {
			rn = t;
		}
	} : a, t && o) {
		let e = h, t = o === !0 ? Infinity : o;
		h = () => sn(e(), t);
	}
	let x = ke(), S = () => {
		m.stop(), x && x.active && u(x.effects, m);
	};
	if (s && t) {
		let e = t;
		t = (...t) => {
			let n = e(...t);
			return S(), n;
		};
	}
	let C = b ? Array(e.length).fill(tn) : tn, w = (e) => {
		if (!(!(m.flags & 1) || !m.dirty && !e)) if (t) {
			let n = m.run();
			if (e || o || y || (b ? n.some((e, t) => D(e, C[t])) : D(n, C))) {
				g && g();
				let e = rn;
				rn = m;
				try {
					let e = [
						n,
						C === tn ? void 0 : b && C[0] === tn ? [] : C,
						v
					];
					C = n, d ? d(t, 3, e) : t(...e);
				} finally {
					rn = e;
				}
			}
		} else m.run();
	};
	return l && l(w), m = new je(h), m.scheduler = c ? () => c(w, !1) : w, v = (e) => an(e, !1, m), g = m.onStop = () => {
		let e = nn.get(m);
		if (e) {
			if (d) d(e, 4);
			else for (let t of e) t();
			nn.delete(m);
		}
	}, t ? i ? w(!0) : C = m.run() : c ? c(w.bind(null, !0), !0) : m.run(), S.pause = m.pause.bind(m), S.resume = m.resume.bind(m), S.stop = S, S;
}
function sn(e, t = Infinity, n) {
	if (t <= 0 || !b(e) || e.__v_skip || (n ||= /* @__PURE__ */ new Map(), (n.get(e) || 0) >= t)) return e;
	if (n.set(e, t), t--, /* @__PURE__ */ P(e)) sn(e.value, t, n);
	else if (p(e)) for (let r = 0; r < e.length; r++) sn(e[r], t, n);
	else if (h(e) || m(e)) e.forEach((e) => {
		sn(e, t, n);
	});
	else if (T(e)) {
		for (let r in e) sn(e[r], t, n);
		for (let r of Object.getOwnPropertySymbols(e)) Object.prototype.propertyIsEnumerable.call(e, r) && sn(e[r], t, n);
	}
	return e;
}
//#endregion
//#region node_modules/@vue/runtime-core/dist/runtime-core.esm-bundler.js
function cn(e, t, n, r) {
	try {
		return r ? e(...r) : e();
	} catch (e) {
		un(e, t, n);
	}
}
function ln(e, t, n, r) {
	if (_(e)) {
		let i = cn(e, t, n, r);
		return i && x(i) && i.catch((e) => {
			un(e, t, n);
		}), i;
	}
	if (p(e)) {
		let i = [];
		for (let a = 0; a < e.length; a++) i.push(ln(e[a], t, n, r));
		return i;
	}
}
function un(e, t, n, i = !0) {
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
			Ke(), cn(o, null, 10, [
				e,
				i,
				a
			]), qe();
			return;
		}
	}
	dn(e, n, a, i, s);
}
function dn(e, t, n, r = !0, i = !1) {
	if (i) throw e;
	console.error(e);
}
var L = [], fn = -1, pn = [], mn = null, hn = 0, gn = /* @__PURE__ */ Promise.resolve(), _n = null;
function vn(e) {
	let t = _n || gn;
	return e ? t.then(this ? e.bind(this) : e) : t;
}
function yn(e) {
	let t = fn + 1, n = L.length;
	for (; t < n;) {
		let r = t + n >>> 1, i = L[r], a = Tn(i);
		a < e || a === e && i.flags & 2 ? t = r + 1 : n = r;
	}
	return t;
}
function bn(e) {
	if (!(e.flags & 1)) {
		let t = Tn(e), n = L[L.length - 1];
		!n || !(e.flags & 2) && t >= Tn(n) ? L.push(e) : L.splice(yn(t), 0, e), e.flags |= 1, xn();
	}
}
function xn() {
	_n ||= gn.then(En);
}
function Sn(e) {
	p(e) ? pn.push(...e) : mn && e.id === -1 ? mn.splice(hn + 1, 0, e) : e.flags & 1 || (pn.push(e), e.flags |= 1), xn();
}
function Cn(e, t, n = fn + 1) {
	for (; n < L.length; n++) {
		let t = L[n];
		if (t && t.flags & 2) {
			if (e && t.id !== e.uid) continue;
			L.splice(n, 1), n--, t.flags & 4 && (t.flags &= -2), t(), t.flags & 4 || (t.flags &= -2);
		}
	}
}
function wn(e) {
	if (pn.length) {
		let e = [...new Set(pn)].sort((e, t) => Tn(e) - Tn(t));
		if (pn.length = 0, mn) {
			mn.push(...e);
			return;
		}
		for (mn = e, hn = 0; hn < mn.length; hn++) {
			let e = mn[hn];
			e.flags & 4 && (e.flags &= -2), e.flags & 8 || e(), e.flags &= -2;
		}
		mn = null, hn = 0;
	}
}
var Tn = (e) => e.id == null ? e.flags & 2 ? -1 : Infinity : e.id;
function En(e) {
	try {
		for (fn = 0; fn < L.length; fn++) {
			let e = L[fn];
			e && !(e.flags & 8) && (e.flags & 4 && (e.flags &= -2), cn(e, e.i, e.i ? 15 : 14), e.flags & 4 || (e.flags &= -2));
		}
	} finally {
		for (; fn < L.length; fn++) {
			let e = L[fn];
			e && (e.flags &= -2);
		}
		fn = -1, L.length = 0, wn(e), _n = null, (L.length || pn.length) && En(e);
	}
}
var Dn = null, On = null;
function kn(e) {
	let t = Dn;
	return Dn = e, On = e && e.type.__scopeId || null, t;
}
function An(e, t = Dn, n) {
	if (!t || e._n) return e;
	let r = (...n) => {
		r._d && Xi(-1);
		let i = kn(t), a;
		try {
			a = e(...n);
		} finally {
			kn(i), r._d && Xi(1);
		}
		return a;
	};
	return r._n = !0, r._c = !0, r._d = !0, r;
}
function R(e, t) {
	if (Dn === null) return e;
	let n = ka(Dn), i = e.dirs ||= [];
	for (let e = 0; e < t.length; e++) {
		let [a, o, s, c = r] = t[e];
		a && (_(a) && (a = {
			mounted: a,
			updated: a
		}), a.deep && sn(o), i.push({
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
function jn(e, t, n, r) {
	let i = e.dirs, a = t && t.dirs;
	for (let o = 0; o < i.length; o++) {
		let s = i[o];
		a && (s.oldValue = a[o].value);
		let c = s.dir[r];
		c && (Ke(), ln(c, n, 8, [
			e.el,
			s,
			e,
			t
		]), qe());
	}
}
function Mn(e, t) {
	if (Y) {
		let n = Y.provides, r = Y.parent && Y.parent.provides;
		r === n && (n = Y.provides = Object.create(r)), n[e] = t;
	}
}
function Nn(e, t, n = !1) {
	let r = ma();
	if (r || ei) {
		let i = ei ? ei._context.provides : r ? r.parent == null || r.ce ? r.vnode.appContext && r.vnode.appContext.provides : r.parent.provides : void 0;
		if (i && e in i) return i[e];
		if (arguments.length > 1) return n && _(t) ? t.call(r && r.proxy) : t;
	}
}
var Pn = /* @__PURE__ */ Symbol.for("v-scx"), Fn = () => Nn(Pn);
function In(e, t, n) {
	return Ln(e, t, n);
}
function Ln(e, t, n = r) {
	let { immediate: i, deep: o, flush: s, once: c } = n, u = l({}, n), d = t && i || !t && s !== "post", f;
	if (ba) {
		if (s === "sync") {
			let e = Fn();
			f = e.__watcherHandles ||= [];
		} else if (!d) {
			let e = () => {};
			return e.stop = a, e.resume = a, e.pause = a, e;
		}
	}
	let p = Y;
	u.call = (e, t, n) => ln(e, p, t, n);
	let m = !1;
	s === "post" ? u.scheduler = (e) => {
		ji(e, p && p.suspense);
	} : s !== "sync" && (m = !0, u.scheduler = (e, t) => {
		t ? e() : bn(e);
	}), u.augmentJob = (e) => {
		t && (e.flags |= 4), m && (e.flags |= 2, p && (e.id = p.uid, e.i = p));
	};
	let h = on(e, t, u);
	return ba && (f ? f.push(h) : d && h()), h;
}
function Rn(e, t, n) {
	let r = this.proxy, i = v(e) ? e.includes(".") ? zn(r, e) : () => r[e] : e.bind(r, r), a;
	_(t) ? a = t : (a = t.handler, n = t);
	let o = _a(this), s = Ln(i, a.bind(r), n);
	return o(), s;
}
function zn(e, t) {
	let n = t.split(".");
	return () => {
		let t = e;
		for (let e = 0; e < n.length && t; e++) t = t[n[e]];
		return t;
	};
}
var Bn = /* @__PURE__ */ Symbol("_vte"), Vn = (e) => e.__isTeleport, Hn = /* @__PURE__ */ Symbol("_leaveCb"), Un = /* @__PURE__ */ Symbol("_enterCb");
function Wn() {
	let e = {
		isMounted: !1,
		isLeaving: !1,
		isUnmounting: !1,
		leavingVNodes: /* @__PURE__ */ new Map()
	};
	return vr(() => {
		e.isMounted = !0;
	}), xr(() => {
		e.isUnmounting = !0;
	}), e;
}
var Gn = [Function, Array], Kn = {
	mode: String,
	appear: Boolean,
	persisted: Boolean,
	onBeforeEnter: Gn,
	onEnter: Gn,
	onAfterEnter: Gn,
	onEnterCancelled: Gn,
	onBeforeLeave: Gn,
	onLeave: Gn,
	onAfterLeave: Gn,
	onLeaveCancelled: Gn,
	onBeforeAppear: Gn,
	onAppear: Gn,
	onAfterAppear: Gn,
	onAppearCancelled: Gn
}, qn = (e) => {
	let t = e.subTree;
	return t.component ? qn(t.component) : t;
}, Jn = {
	name: "BaseTransition",
	props: Kn,
	setup(e, { slots: t }) {
		let n = ma(), r = Wn();
		return () => {
			let i = t.default && nr(t.default(), !0), a = i && i.length ? Yn(i) : n.subTree ? J() : void 0;
			if (!a) return;
			let o = /* @__PURE__ */ N(e), { mode: s } = o;
			if (r.isLeaving) return $n(a);
			let c = er(a);
			if (!c) return $n(a);
			let l = Qn(c, o, r, n, (e) => l = e);
			c.type !== H && tr(c, l);
			let u = n.subTree && er(n.subTree);
			if (u && u.type !== H && !ea(u, c) && qn(n).type !== H) {
				let e = Qn(u, o, r, n);
				if (tr(u, e), s === "out-in" && c.type !== H) return r.isLeaving = !0, e.afterLeave = () => {
					r.isLeaving = !1, n.job.flags & 8 || n.update(), delete e.afterLeave, u = void 0;
				}, $n(a);
				s === "in-out" && c.type !== H ? e.delayLeave = (e, t, n) => {
					let i = Zn(r, u);
					i[String(u.key)] = u, e[Hn] = () => {
						t(), e[Hn] = void 0, delete l.delayedLeave, u = void 0;
					}, l.delayedLeave = () => {
						n(), delete l.delayedLeave, u = void 0;
					};
				} : u = void 0;
			} else u &&= void 0;
			return a;
		};
	}
};
function Yn(e) {
	let t = e[0];
	if (e.length > 1) {
		for (let n of e) if (n.type !== H) {
			t = n;
			break;
		}
	}
	return t;
}
var Xn = Jn;
function Zn(e, t) {
	let { leavingVNodes: n } = e, r = n.get(t.type);
	return r || (r = /* @__PURE__ */ Object.create(null), n.set(t.type, r)), r;
}
function Qn(e, t, n, r, i) {
	let { appear: a, mode: o, persisted: s = !1, onBeforeEnter: c, onEnter: l, onAfterEnter: u, onEnterCancelled: d, onBeforeLeave: f, onLeave: m, onAfterLeave: h, onLeaveCancelled: g, onBeforeAppear: _, onAppear: v, onAfterAppear: y, onAppearCancelled: b } = t, x = String(e.key), S = Zn(n, e), C = (e, t) => {
		e && ln(e, r, 9, t);
	}, w = (e, t) => {
		let n = t[1];
		C(e, t), p(e) ? e.every((e) => e.length <= 1) && n() : e.length <= 1 && n();
	}, T = {
		mode: o,
		persisted: s,
		beforeEnter(t) {
			let r = c;
			if (!n.isMounted) if (a) r = _ || c;
			else return;
			t[Hn] && t[Hn](!0);
			let i = S[x];
			i && ea(e, i) && i.el[Hn] && i.el[Hn](), C(r, [t]);
		},
		enter(t) {
			if (S[x] === e) return;
			let r = l, i = u, o = d;
			if (!n.isMounted) if (a) r = v || l, i = y || u, o = b || d;
			else return;
			let s = !1;
			t[Un] = (e) => {
				s || (s = !0, C(e ? o : i, [t]), T.delayedLeave && T.delayedLeave(), t[Un] = void 0);
			};
			let c = t[Un].bind(null, !1);
			r ? w(r, [t, c]) : c();
		},
		leave(t, r) {
			let i = String(e.key);
			if (t[Un] && t[Un](!0), n.isUnmounting) return r();
			C(f, [t]);
			let a = !1;
			t[Hn] = (n) => {
				a || (a = !0, r(), C(n ? g : h, [t]), t[Hn] = void 0, S[i] === e && delete S[i]);
			};
			let o = t[Hn].bind(null, !1);
			S[i] = e, m ? w(m, [t, o]) : o();
		},
		clone(e) {
			let a = Qn(e, t, n, r, i);
			return i && i(a), a;
		}
	};
	return T;
}
function $n(e) {
	if (ur(e)) return e = aa(e), e.children = null, e;
}
function er(e) {
	if (!ur(e)) return Vn(e.type) && e.children ? Yn(e.children) : e;
	if (e.component) return e.component.subTree;
	let { shapeFlag: t, children: n } = e;
	if (n) {
		if (t & 16) return n[0];
		if (t & 32 && _(n.default)) return n.default();
	}
}
function tr(e, t) {
	e.shapeFlag & 6 && e.component ? (e.transition = t, tr(e.component.subTree, t)) : e.shapeFlag & 128 ? (e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback)) : e.transition = t;
}
function nr(e, t = !1, n) {
	let r = [], i = 0;
	for (let a = 0; a < e.length; a++) {
		let o = e[a], s = n == null ? o.key : String(n) + String(o.key == null ? a : o.key);
		o.type === V ? (o.patchFlag & 128 && i++, r = r.concat(nr(o.children, t, s))) : (t || o.type !== H) && r.push(s == null ? o : aa(o, { key: s }));
	}
	if (i > 1) for (let e = 0; e < r.length; e++) r[e].patchFlag = -2;
	return r;
}
function rr() {
	let e = ma();
	return e ? (e.appContext.config.idPrefix || "v") + "-" + e.ids[0] + e.ids[1]++ : "";
}
function ir(e) {
	e.ids = [
		e.ids[0] + e.ids[2]++ + "-",
		0,
		0
	];
}
function ar(e, t) {
	let n;
	return !!((n = Object.getOwnPropertyDescriptor(e, t)) && !n.configurable);
}
var or = /* @__PURE__ */ new WeakMap();
function sr(e, t, n, i, a = !1) {
	if (p(e)) {
		e.forEach((e, r) => sr(e, t && (p(t) ? t[r] : t), n, i, a));
		return;
	}
	if (lr(i) && !a) {
		i.shapeFlag & 512 && i.type.__asyncResolved && i.component.subTree.component && sr(e, t, n, i.component.subTree);
		return;
	}
	let s = i.shapeFlag & 4 ? ka(i.component) : i.el, c = a ? null : s, { i: l, r: d } = e, m = t && t.r, h = l.refs === r ? l.refs = {} : l.refs, g = l.setupState, y = /* @__PURE__ */ N(g), b = g === r ? o : (e) => ar(h, e) ? !1 : f(y, e), x = (e, t) => !(t && ar(h, t));
	if (m != null && m !== d) {
		if (cr(t), v(m)) h[m] = null, b(m) && (g[m] = null);
		else if (/* @__PURE__ */ P(m)) {
			let e = t;
			x(m, e.k) && (m.value = null), e.k && (h[e.k] = null);
		}
	}
	if (_(d)) cn(d, l, 12, [c, h]);
	else {
		let t = v(d), r = /* @__PURE__ */ P(d);
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
					i(), or.delete(e);
				};
				t.id = -1, or.set(e, t), ji(t, n);
			} else cr(e), i();
		}
	}
}
function cr(e) {
	let t = or.get(e);
	t && (t.flags |= 8, or.delete(e));
}
pe().requestIdleCallback, pe().cancelIdleCallback;
var lr = (e) => !!e.type.__asyncLoader, ur = (e) => e.type.__isKeepAlive;
function dr(e, t) {
	pr(e, "a", t);
}
function fr(e, t) {
	pr(e, "da", t);
}
function pr(e, t, n = Y) {
	let r = e.__wdc ||= () => {
		let t = n;
		for (; t;) {
			if (t.isDeactivated) return;
			t = t.parent;
		}
		return e();
	};
	if (hr(t, r, n), n) {
		let e = n.parent;
		for (; e && e.parent;) ur(e.parent.vnode) && mr(r, t, n, e), e = e.parent;
	}
}
function mr(e, t, n, r) {
	let i = hr(t, e, r, !0);
	Sr(() => {
		u(r[t], i);
	}, n);
}
function hr(e, t, n = Y, r = !1) {
	if (n) {
		let i = n[e] || (n[e] = []), a = t.__weh ||= (...r) => {
			Ke();
			let i = _a(n), a = ln(t, n, e, r);
			return i(), qe(), a;
		};
		return r ? i.unshift(a) : i.push(a), a;
	}
}
var gr = (e) => (t, n = Y) => {
	(!ba || e === "sp") && hr(e, (...e) => t(...e), n);
}, _r = gr("bm"), vr = gr("m"), yr = gr("bu"), br = gr("u"), xr = gr("bum"), Sr = gr("um"), Cr = gr("sp"), wr = gr("rtg"), Tr = gr("rtc");
function Er(e, t = Y) {
	hr("ec", e, t);
}
var Dr = "components", Or = /* @__PURE__ */ Symbol.for("v-ndc");
function kr(e) {
	return v(e) ? Ar(Dr, e, !1) || e : e || Or;
}
function Ar(e, t, n = !0, r = !1) {
	let i = Dn || Y;
	if (i) {
		let n = i.type;
		if (e === Dr) {
			let e = Aa(n, !1);
			if (e && (e === t || e === E(t) || e === oe(E(t)))) return n;
		}
		let a = jr(i[e] || n[e], t) || jr(i.appContext[e], t);
		return !a && r ? n : a;
	}
}
function jr(e, t) {
	return e && (e[t] || e[E(t)] || e[oe(E(t))]);
}
function z(e, t, n, r) {
	let i, a = n && n[r], o = p(e);
	if (o || v(e)) {
		let n = o && /* @__PURE__ */ Vt(e), r = !1, s = !1;
		n && (r = !/* @__PURE__ */ Ut(e), s = /* @__PURE__ */ Ht(e), e = at(e)), i = Array(e.length);
		for (let n = 0, o = e.length; n < o; n++) i[n] = t(r ? s ? qt(Kt(e[n])) : Kt(e[n]) : e[n], n, void 0, a && a[n]);
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
var Mr = (e) => e ? ya(e) ? ka(e) : Mr(e.parent) : null, Nr = /* @__PURE__ */ l(/* @__PURE__ */ Object.create(null), {
	$: (e) => e,
	$el: (e) => e.vnode.el,
	$data: (e) => e.data,
	$props: (e) => e.props,
	$attrs: (e) => e.attrs,
	$slots: (e) => e.slots,
	$refs: (e) => e.refs,
	$parent: (e) => Mr(e.parent),
	$root: (e) => Mr(e.root),
	$host: (e) => e.ce,
	$emit: (e) => e.emit,
	$options: (e) => Hr(e),
	$forceUpdate: (e) => e.f ||= () => {
		bn(e.update);
	},
	$nextTick: (e) => e.n ||= vn.bind(e.proxy),
	$watch: (e) => Rn.bind(e)
}), Pr = (e, t) => e !== r && !e.__isScriptSetup && f(e, t), Fr = {
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
			else if (Pr(i, t)) return s[t] = 1, i[t];
			else if (a !== r && f(a, t)) return s[t] = 2, a[t];
			else if (f(o, t)) return s[t] = 3, o[t];
			else if (n !== r && f(n, t)) return s[t] = 4, n[t];
			else Lr && (s[t] = 0);
		}
		let u = Nr[t], d, p;
		if (u) return t === "$attrs" && M(e.attrs, "get", ""), u(e);
		if ((d = c.__cssModules) && (d = d[t])) return d;
		if (n !== r && f(n, t)) return s[t] = 4, n[t];
		if (p = l.config.globalProperties, f(p, t)) return p[t];
	},
	set({ _: e }, t, n) {
		let { data: i, setupState: a, ctx: o } = e;
		return Pr(a, t) ? (a[t] = n, !0) : i !== r && f(i, t) ? (i[t] = n, !0) : f(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (o[t] = n, !0);
	},
	has({ _: { data: e, setupState: t, accessCache: n, ctx: i, appContext: a, props: o, type: s } }, c) {
		let l;
		return !!(n[c] || e !== r && c[0] !== "$" && f(e, c) || Pr(t, c) || f(o, c) || f(i, c) || f(Nr, c) || f(a.config.globalProperties, c) || (l = s.__cssModules) && l[c]);
	},
	defineProperty(e, t, n) {
		return n.get == null ? f(n, "value") && this.set(e, t, n.value, null) : e._.accessCache[t] = 0, Reflect.defineProperty(e, t, n);
	}
};
function Ir(e) {
	return p(e) ? e.reduce((e, t) => (e[t] = null, e), {}) : e;
}
var Lr = !0;
function Rr(e) {
	let t = Hr(e), n = e.proxy, r = e.ctx;
	Lr = !1, t.beforeCreate && Br(t.beforeCreate, e, "bc");
	let { data: i, computed: o, methods: s, watch: c, provide: l, inject: u, created: d, beforeMount: f, mounted: m, beforeUpdate: h, updated: g, activated: v, deactivated: y, beforeDestroy: x, beforeUnmount: S, destroyed: C, unmounted: w, render: T, renderTracked: ee, renderTriggered: te, errorCaptured: ne, serverPrefetch: re, expose: E, inheritAttrs: ie, components: ae, directives: oe, filters: se } = t;
	if (u && zr(u, r, null), s) for (let e in s) {
		let t = s[e];
		_(t) && (r[e] = t.bind(n));
	}
	if (i) {
		let t = i.call(n, n);
		b(t) && (e.data = /* @__PURE__ */ Lt(t));
	}
	if (Lr = !0, o) for (let e in o) {
		let t = o[e], i = X({
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
	if (c) for (let e in c) Vr(c[e], r, n, e);
	if (l) {
		let e = _(l) ? l.call(n) : l;
		Reflect.ownKeys(e).forEach((t) => {
			Mn(t, e[t]);
		});
	}
	d && Br(d, e, "c");
	function D(e, t) {
		p(t) ? t.forEach((t) => e(t.bind(n))) : t && e(t.bind(n));
	}
	if (D(_r, f), D(vr, m), D(yr, h), D(br, g), D(dr, v), D(fr, y), D(Er, ne), D(Tr, ee), D(wr, te), D(xr, S), D(Sr, w), D(Cr, re), p(E)) if (E.length) {
		let t = e.exposed ||= {};
		E.forEach((e) => {
			Object.defineProperty(t, e, {
				get: () => n[e],
				set: (t) => n[e] = t,
				enumerable: !0
			});
		});
	} else e.exposed ||= {};
	T && e.render === a && (e.render = T), ie != null && (e.inheritAttrs = ie), ae && (e.components = ae), oe && (e.directives = oe), re && ir(e);
}
function zr(e, t, n = a) {
	p(e) && (e = qr(e));
	for (let n in e) {
		let r = e[n], i;
		i = b(r) ? "default" in r ? Nn(r.from || n, r.default, !0) : Nn(r.from || n) : Nn(r), /* @__PURE__ */ P(i) ? Object.defineProperty(t, n, {
			enumerable: !0,
			configurable: !0,
			get: () => i.value,
			set: (e) => i.value = e
		}) : t[n] = i;
	}
}
function Br(e, t, n) {
	ln(p(e) ? e.map((e) => e.bind(t.proxy)) : e.bind(t.proxy), t, n);
}
function Vr(e, t, n, r) {
	let i = r.includes(".") ? zn(n, r) : () => n[r];
	if (v(e)) {
		let n = t[e];
		_(n) && In(i, n);
	} else if (_(e)) In(i, e.bind(n));
	else if (b(e)) if (p(e)) e.forEach((e) => Vr(e, t, n, r));
	else {
		let r = _(e.handler) ? e.handler.bind(n) : t[e.handler];
		_(r) && In(i, r, e);
	}
}
function Hr(e) {
	let t = e.type, { mixins: n, extends: r } = t, { mixins: i, optionsCache: a, config: { optionMergeStrategies: o } } = e.appContext, s = a.get(t), c;
	return s ? c = s : !i.length && !n && !r ? c = t : (c = {}, i.length && i.forEach((e) => Ur(c, e, o, !0)), Ur(c, t, o)), b(t) && a.set(t, c), c;
}
function Ur(e, t, n, r = !1) {
	let { mixins: i, extends: a } = t;
	a && Ur(e, a, n, !0), i && i.forEach((t) => Ur(e, t, n, !0));
	for (let i in t) if (!(r && i === "expose")) {
		let r = Wr[i] || n && n[i];
		e[i] = r ? r(e[i], t[i]) : t[i];
	}
	return e;
}
var Wr = {
	data: Gr,
	props: Yr,
	emits: Yr,
	methods: Jr,
	computed: Jr,
	beforeCreate: B,
	created: B,
	beforeMount: B,
	mounted: B,
	beforeUpdate: B,
	updated: B,
	beforeDestroy: B,
	beforeUnmount: B,
	destroyed: B,
	unmounted: B,
	activated: B,
	deactivated: B,
	errorCaptured: B,
	serverPrefetch: B,
	components: Jr,
	directives: Jr,
	watch: Xr,
	provide: Gr,
	inject: Kr
};
function Gr(e, t) {
	return t ? e ? function() {
		return l(_(e) ? e.call(this, this) : e, _(t) ? t.call(this, this) : t);
	} : t : e;
}
function Kr(e, t) {
	return Jr(qr(e), qr(t));
}
function qr(e) {
	if (p(e)) {
		let t = {};
		for (let n = 0; n < e.length; n++) t[e[n]] = e[n];
		return t;
	}
	return e;
}
function B(e, t) {
	return e ? [...new Set([].concat(e, t))] : t;
}
function Jr(e, t) {
	return e ? l(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function Yr(e, t) {
	return e ? p(e) && p(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : l(/* @__PURE__ */ Object.create(null), Ir(e), Ir(t ?? {})) : t;
}
function Xr(e, t) {
	if (!e) return t;
	if (!t) return e;
	let n = l(/* @__PURE__ */ Object.create(null), e);
	for (let r in t) n[r] = B(e[r], t[r]);
	return n;
}
function Zr() {
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
var Qr = 0;
function $r(e, t) {
	return function(n, r = null) {
		_(n) || (n = l({}, n)), r != null && !b(r) && (r = null);
		let i = Zr(), a = /* @__PURE__ */ new WeakSet(), o = [], s = !1, c = i.app = {
			_uid: Qr++,
			_component: n,
			_props: r,
			_container: null,
			_context: i,
			_instance: null,
			version: Na,
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
					let u = c._ceVNode || K(n, r);
					return u.appContext = i, l === !0 ? l = "svg" : l === !1 && (l = void 0), o && t ? t(u, a) : e(u, a, l), s = !0, c._container = a, a.__vue_app__ = c, ka(u.component);
				}
			},
			onUnmount(e) {
				o.push(e);
			},
			unmount() {
				s && (ln(o, c._instance, 16), e(null, c._container), delete c._container.__vue_app__);
			},
			provide(e, t) {
				return i.provides[e] = t, c;
			},
			runWithContext(e) {
				let t = ei;
				ei = c;
				try {
					return e();
				} finally {
					ei = t;
				}
			}
		};
		return c;
	};
}
var ei = null, ti = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${E(t)}Modifiers`] || e[`${ae(t)}Modifiers`];
function ni(e, t, ...n) {
	if (e.isUnmounted) return;
	let i = e.vnode.props || r, a = n, o = t.startsWith("update:"), s = o && ti(i, t.slice(7));
	s && (s.trim && (a = n.map((e) => v(e) ? e.trim() : e)), s.number && (a = n.map(ue)));
	let c, l = i[c = se(t)] || i[c = se(E(t))];
	!l && o && (l = i[c = se(ae(t))]), l && ln(l, e, 6, a);
	let u = i[c + "Once"];
	if (u) {
		if (!e.emitted) e.emitted = {};
		else if (e.emitted[c]) return;
		e.emitted[c] = !0, ln(u, e, 6, a);
	}
}
var ri = /* @__PURE__ */ new WeakMap();
function ii(e, t, n = !1) {
	let r = n ? ri : t.emitsCache, i = r.get(e);
	if (i !== void 0) return i;
	let a = e.emits, o = {}, s = !1;
	if (!_(e)) {
		let r = (e) => {
			let n = ii(e, t, !0);
			n && (s = !0, l(o, n));
		};
		!n && t.mixins.length && t.mixins.forEach(r), e.extends && r(e.extends), e.mixins && e.mixins.forEach(r);
	}
	return !a && !s ? (b(e) && r.set(e, null), null) : (p(a) ? a.forEach((e) => o[e] = null) : l(o, a), b(e) && r.set(e, o), o);
}
function ai(e, t) {
	return !e || !s(t) ? !1 : (t = t.slice(2).replace(/Once$/, ""), f(e, t[0].toLowerCase() + t.slice(1)) || f(e, ae(t)) || f(e, t));
}
function oi(e) {
	let { type: t, vnode: n, proxy: r, withProxy: i, propsOptions: [a], slots: o, attrs: s, emit: l, render: u, renderCache: d, props: f, data: p, setupState: m, ctx: h, inheritAttrs: g } = e, _ = kn(e), v, y;
	try {
		if (n.shapeFlag & 4) {
			let e = i || r, t = e;
			v = oa(u.call(t, e, d, f, m, p, h)), y = s;
		} else {
			let e = t;
			v = oa(e.length > 1 ? e(f, {
				attrs: s,
				slots: o,
				emit: l
			}) : e(f, null)), y = t.props ? s : si(s);
		}
	} catch (t) {
		Ki.length = 0, un(t, e, 1), v = K(H);
	}
	let b = v;
	if (y && g !== !1) {
		let e = Object.keys(y), { shapeFlag: t } = b;
		e.length && t & 7 && (a && e.some(c) && (y = ci(y, a)), b = aa(b, y, !1, !0));
	}
	return n.dirs && (b = aa(b, null, !1, !0), b.dirs = b.dirs ? b.dirs.concat(n.dirs) : n.dirs), n.transition && tr(b, n.transition), v = b, kn(_), v;
}
var si = (e) => {
	let t;
	for (let n in e) (n === "class" || n === "style" || s(n)) && ((t ||= {})[n] = e[n]);
	return t;
}, ci = (e, t) => {
	let n = {};
	for (let r in e) (!c(r) || !(r.slice(9) in t)) && (n[r] = e[r]);
	return n;
};
function li(e, t, n) {
	let { props: r, children: i, component: a } = e, { props: o, children: s, patchFlag: c } = t, l = a.emitsOptions;
	if (t.dirs || t.transition) return !0;
	if (n && c >= 0) {
		if (c & 1024) return !0;
		if (c & 16) return r ? ui(r, o, l) : !!o;
		if (c & 8) {
			let e = t.dynamicProps;
			for (let t = 0; t < e.length; t++) {
				let n = e[t];
				if (di(o, r, n) && !ai(l, n)) return !0;
			}
		}
	} else return (i || s) && (!s || !s.$stable) ? !0 : r === o ? !1 : r ? o ? ui(r, o, l) : !0 : !!o;
	return !1;
}
function ui(e, t, n) {
	let r = Object.keys(t);
	if (r.length !== Object.keys(e).length) return !0;
	for (let i = 0; i < r.length; i++) {
		let a = r[i];
		if (di(t, e, a) && !ai(n, a)) return !0;
	}
	return !1;
}
function di(e, t, n) {
	let r = e[n], i = t[n];
	return n === "style" && b(r) && b(i) ? !Ce(r, i) : r !== i;
}
function fi({ vnode: e, parent: t, suspense: n }, r) {
	for (; t;) {
		let n = t.subTree;
		if (n.suspense && n.suspense.activeBranch === e && (n.suspense.vnode.el = n.el = r, e = n), n === e) (e = t.vnode).el = r, t = t.parent;
		else break;
	}
	n && n.activeBranch === e && (n.vnode.el = r);
}
var pi = {}, mi = () => Object.create(pi), hi = (e) => Object.getPrototypeOf(e) === pi;
function gi(e, t, n, r = !1) {
	let i = {}, a = mi();
	e.propsDefaults = /* @__PURE__ */ Object.create(null), vi(e, t, i, a);
	for (let t in e.propsOptions[0]) t in i || (i[t] = void 0);
	n ? e.props = r ? i : /* @__PURE__ */ Rt(i) : e.type.props ? e.props = i : e.props = a, e.attrs = a;
}
function _i(e, t, n, r) {
	let { props: i, attrs: a, vnode: { patchFlag: o } } = e, s = /* @__PURE__ */ N(i), [c] = e.propsOptions, l = !1;
	if ((r || o > 0) && !(o & 16)) {
		if (o & 8) {
			let n = e.vnode.dynamicProps;
			for (let r = 0; r < n.length; r++) {
				let o = n[r];
				if (ai(e.emitsOptions, o)) continue;
				let u = t[o];
				if (c) if (f(a, o)) u !== a[o] && (a[o] = u, l = !0);
				else {
					let t = E(o);
					i[t] = yi(c, s, t, u, e, !1);
				}
				else u !== a[o] && (a[o] = u, l = !0);
			}
		}
	} else {
		vi(e, t, i, a) && (l = !0);
		let r;
		for (let a in s) (!t || !f(t, a) && ((r = ae(a)) === a || !f(t, r))) && (c ? n && (n[a] !== void 0 || n[r] !== void 0) && (i[a] = yi(c, s, a, void 0, e, !0)) : delete i[a]);
		if (a !== s) for (let e in a) (!t || !f(t, e)) && (delete a[e], l = !0);
	}
	l && rt(e.attrs, "set", "");
}
function vi(e, t, n, i) {
	let [a, o] = e.propsOptions, s = !1, c;
	if (t) for (let r in t) {
		if (te(r)) continue;
		let l = t[r], u;
		a && f(a, u = E(r)) ? !o || !o.includes(u) ? n[u] = l : (c ||= {})[u] = l : ai(e.emitsOptions, r) || (!(r in i) || l !== i[r]) && (i[r] = l, s = !0);
	}
	if (o) {
		let t = /* @__PURE__ */ N(n), i = c || r;
		for (let r = 0; r < o.length; r++) {
			let s = o[r];
			n[s] = yi(a, t, s, i[s], e, !f(i, s));
		}
	}
	return s;
}
function yi(e, t, n, r, i, a) {
	let o = e[n];
	if (o != null) {
		let e = f(o, "default");
		if (e && r === void 0) {
			let e = o.default;
			if (o.type !== Function && !o.skipFactory && _(e)) {
				let { propsDefaults: a } = i;
				if (n in a) r = a[n];
				else {
					let o = _a(i);
					r = a[n] = e.call(null, t), o();
				}
			} else r = e;
			i.ce && i.ce._setProp(n, r);
		}
		o[0] && (a && !e ? r = !1 : o[1] && (r === "" || r === ae(n)) && (r = !0));
	}
	return r;
}
var bi = /* @__PURE__ */ new WeakMap();
function xi(e, t, n = !1) {
	let a = n ? bi : t.propsCache, o = a.get(e);
	if (o) return o;
	let s = e.props, c = {}, u = [], d = !1;
	if (!_(e)) {
		let r = (e) => {
			d = !0;
			let [n, r] = xi(e, t, !0);
			l(c, n), r && u.push(...r);
		};
		!n && t.mixins.length && t.mixins.forEach(r), e.extends && r(e.extends), e.mixins && e.mixins.forEach(r);
	}
	if (!s && !d) return b(e) && a.set(e, i), i;
	if (p(s)) for (let e = 0; e < s.length; e++) {
		let t = E(s[e]);
		Si(t) && (c[t] = r);
	}
	else if (s) for (let e in s) {
		let t = E(e);
		if (Si(t)) {
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
function Si(e) {
	return e[0] !== "$" && !te(e);
}
var Ci = (e) => e === "_" || e === "_ctx" || e === "$stable", wi = (e) => p(e) ? e.map(oa) : [oa(e)], Ti = (e, t, n) => {
	if (t._n) return t;
	let r = An((...e) => wi(t(...e)), n);
	return r._c = !1, r;
}, Ei = (e, t, n) => {
	let r = e._ctx;
	for (let n in e) {
		if (Ci(n)) continue;
		let i = e[n];
		if (_(i)) t[n] = Ti(n, i, r);
		else if (i != null) {
			let e = wi(i);
			t[n] = () => e;
		}
	}
}, Di = (e, t) => {
	let n = wi(t);
	e.slots.default = () => n;
}, Oi = (e, t, n) => {
	for (let r in t) (n || !Ci(r)) && (e[r] = t[r]);
}, ki = (e, t, n) => {
	let r = e.slots = mi();
	if (e.vnode.shapeFlag & 32) {
		let e = t._;
		e ? (Oi(r, t, n), n && le(r, "_", e, !0)) : Ei(t, r);
	} else t && Di(e, t);
}, Ai = (e, t, n) => {
	let { vnode: i, slots: a } = e, o = !0, s = r;
	if (i.shapeFlag & 32) {
		let e = t._;
		e ? n && e === 1 ? o = !1 : Oi(a, t, n) : (o = !t.$stable, Ei(t, a)), s = t;
	} else t && (Di(e, t), s = { default: 1 });
	if (o) for (let e in a) !Ci(e) && s[e] == null && delete a[e];
}, ji = Ui;
function Mi(e) {
	return Ni(e);
}
function Ni(e, t) {
	let n = pe();
	n.__VUE__ = !0;
	let { insert: o, remove: s, patchProp: c, createElement: l, createText: u, createComment: d, setText: f, setElementText: p, parentNode: m, nextSibling: h, setScopeId: g = a, insertStaticContent: _ } = e, v = (e, t, n, r = null, i = null, a = null, o = void 0, s = null, c = !!t.dynamicChildren) => {
		if (e === t) return;
		e && !ea(e, t) && (r = be(e), ge(e, i, a, !0), e = null), t.patchFlag === -2 && (c = !1, t.dynamicChildren = null);
		let { type: l, ref: u, shapeFlag: d } = t;
		switch (l) {
			case Wi:
				y(e, t, n, r);
				break;
			case H:
				b(e, t, n, r);
				break;
			case Gi:
				e ?? x(t, n, r, o);
				break;
			case V:
				ae(e, t, n, r, i, a, o, s, c);
				break;
			default: d & 1 ? w(e, t, n, r, i, a, o, s, c) : d & 6 ? oe(e, t, n, r, i, a, o, s, c) : (d & 64 || d & 128) && l.process(e, t, n, r, i, a, o, s, c, Ce);
		}
		u != null && i ? sr(u, e && e.ref, a, t || e, !t) : u == null && e && e.ref != null && sr(e.ref, null, a, e, !0);
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
		if (t.type === "svg" ? o = "svg" : t.type === "math" && (o = "mathml"), e == null) T(t, n, r, i, a, o, s, c);
		else {
			let n = e.el && e.el._isVueCE ? e.el : null;
			try {
				n && n._beginPatch(), re(e, t, i, a, o, s, c);
			} finally {
				n && n._endPatch();
			}
		}
	}, T = (e, t, n, r, i, a, s, u) => {
		let d, f, { props: m, shapeFlag: h, transition: g, dirs: _ } = e;
		if (d = e.el = l(e.type, a, m && m.is, m), h & 8 ? p(d, e.children) : h & 16 && ne(e.children, d, null, r, i, Pi(e, a), s, u), _ && jn(e, null, r, "created"), ee(d, e, e.scopeId, s, r), m) {
			for (let e in m) e !== "value" && !te(e) && c(d, e, null, m[e], a, r);
			"value" in m && c(d, "value", null, m.value, a), (f = m.onVnodeBeforeMount) && ua(f, r, e);
		}
		_ && jn(e, null, r, "beforeMount");
		let v = Ii(i, g);
		v && g.beforeEnter(d), o(d, t, n), ((f = m && m.onVnodeMounted) || v || _) && ji(() => {
			try {
				f && ua(f, r, e), v && g.enter(d), _ && jn(e, null, r, "mounted");
			} finally {}
		}, i);
	}, ee = (e, t, n, r, i) => {
		if (n && g(e, n), r) for (let t = 0; t < r.length; t++) g(e, r[t]);
		if (i) {
			let n = i.subTree;
			if (t === n || Hi(n.type) && (n.ssContent === t || n.ssFallback === t)) {
				let t = i.vnode;
				ee(e, t, t.scopeId, t.slotScopeIds, i.parent);
			}
		}
	}, ne = (e, t, n, r, i, a, o, s, c = 0) => {
		for (let l = c; l < e.length; l++) v(null, e[l] = s ? sa(e[l]) : oa(e[l]), t, n, r, i, a, o, s);
	}, re = (e, t, n, i, a, o, s) => {
		let l = t.el = e.el, { patchFlag: u, dynamicChildren: d, dirs: f } = t;
		u |= e.patchFlag & 16;
		let m = e.props || r, h = t.props || r, g;
		if (n && Fi(n, !1), (g = h.onVnodeBeforeUpdate) && ua(g, n, t, e), f && jn(t, e, n, "beforeUpdate"), n && Fi(n, !0), (m.innerHTML && h.innerHTML == null || m.textContent && h.textContent == null) && p(l, ""), d ? E(e.dynamicChildren, d, l, n, i, Pi(t, a), o) : s || de(e, t, l, null, n, i, Pi(t, a), o, !1), u > 0) {
			if (u & 16) ie(l, m, h, n, a);
			else if (u & 2 && m.class !== h.class && c(l, "class", null, h.class, a), u & 4 && c(l, "style", m.style, h.style, a), u & 8) {
				let e = t.dynamicProps;
				for (let t = 0; t < e.length; t++) {
					let r = e[t], i = m[r], o = h[r];
					(o !== i || r === "value") && c(l, r, i, o, a, n);
				}
			}
			u & 1 && e.children !== t.children && p(l, t.children);
		} else !s && d == null && ie(l, m, h, n, a);
		((g = h.onVnodeUpdated) || f) && ji(() => {
			g && ua(g, n, t, e), f && jn(t, e, n, "updated");
		}, i);
	}, E = (e, t, n, r, i, a, o) => {
		for (let s = 0; s < t.length; s++) {
			let c = e[s], l = t[s];
			v(c, l, c.el && (c.type === V || !ea(c, l) || c.shapeFlag & 198) ? m(c.el) : n, null, r, i, a, o, !0);
		}
	}, ie = (e, t, n, i, a) => {
		if (t !== n) {
			if (t !== r) for (let r in t) !te(r) && !(r in n) && c(e, r, t[r], null, a, i);
			for (let r in n) {
				if (te(r)) continue;
				let o = n[r], s = t[r];
				o !== s && r !== "value" && c(e, r, s, o, a, i);
			}
			"value" in n && c(e, "value", t.value, n.value, a);
		}
	}, ae = (e, t, n, r, i, a, s, c, l) => {
		let d = t.el = e ? e.el : u(""), f = t.anchor = e ? e.anchor : u(""), { patchFlag: p, dynamicChildren: m, slotScopeIds: h } = t;
		h && (c = c ? c.concat(h) : h), e == null ? (o(d, n, r), o(f, n, r), ne(t.children || [], n, f, i, a, s, c, l)) : p > 0 && p & 64 && m && e.dynamicChildren && e.dynamicChildren.length === m.length ? (E(e.dynamicChildren, m, n, i, a, s, c), (t.key != null || i && t === i.subTree) && Li(e, t, !0)) : de(e, t, n, f, i, a, s, c, l);
	}, oe = (e, t, n, r, i, a, o, s, c) => {
		t.slotScopeIds = s, e == null ? t.shapeFlag & 512 ? i.ctx.activate(t, n, r, o, c) : se(t, n, r, i, a, o, c) : D(e, t, c);
	}, se = (e, t, n, r, i, a, o) => {
		let s = e.component = pa(e, r, i);
		if (ur(e) && (s.ctx.renderer = Ce), xa(s, !1, o), s.asyncDep) {
			if (i && i.registerDep(s, le, o), !e.el) {
				let r = s.subTree = K(H);
				b(null, r, t, n), e.placeholder = r.el;
			}
		} else le(s, e, t, n, i, a, o);
	}, D = (e, t, n) => {
		let r = t.component = e.component;
		if (li(e, t, n)) if (r.asyncDep && !r.asyncResolved) {
			ue(r, t, n);
			return;
		} else r.next = t, r.update();
		else t.el = e.el, r.vnode = t;
	}, le = (e, t, n, r, i, a, o) => {
		let s = () => {
			if (e.isMounted) {
				let { next: t, bu: n, u: r, parent: s, vnode: c } = e;
				{
					let n = zi(e);
					if (n) {
						t && (t.el = c.el, ue(e, t, o)), n.asyncDep.then(() => {
							ji(() => {
								e.isUnmounted || l();
							}, i);
						});
						return;
					}
				}
				let u = t, d;
				Fi(e, !1), t ? (t.el = c.el, ue(e, t, o)) : t = c, n && ce(n), (d = t.props && t.props.onVnodeBeforeUpdate) && ua(d, s, t, c), Fi(e, !0);
				let f = oi(e), p = e.subTree;
				e.subTree = f, v(p, f, m(p.el), be(p), e, i, a), t.el = f.el, u === null && fi(e, f.el), r && ji(r, i), (d = t.props && t.props.onVnodeUpdated) && ji(() => ua(d, s, t, c), i);
			} else {
				let o, { el: s, props: c } = t, { bm: l, m: u, parent: d, root: f, type: p } = e, m = lr(t);
				if (Fi(e, !1), l && ce(l), !m && (o = c && c.onVnodeBeforeMount) && ua(o, d, t), Fi(e, !0), s && Te) {
					let t = () => {
						e.subTree = oi(e), Te(s, e.subTree, e, i, null);
					};
					m && p.__asyncHydrate ? p.__asyncHydrate(s, e, t) : t();
				} else {
					f.ce && f.ce._hasShadowRoot() && f.ce._injectChildStyle(p, e.parent ? e.parent.type : void 0);
					let o = e.subTree = oi(e);
					v(null, o, n, r, e, i, a), t.el = o.el;
				}
				if (u && ji(u, i), !m && (o = c && c.onVnodeMounted)) {
					let e = t;
					ji(() => ua(o, d, e), i);
				}
				(t.shapeFlag & 256 || d && lr(d.vnode) && d.vnode.shapeFlag & 256) && e.a && ji(e.a, i), e.isMounted = !0, t = n = r = null;
			}
		};
		e.scope.on();
		let c = e.effect = new je(s);
		e.scope.off();
		let l = e.update = c.run.bind(c), u = e.job = c.runIfDirty.bind(c);
		u.i = e, u.id = e.uid, c.scheduler = () => bn(u), Fi(e, !0), l();
	}, ue = (e, t, n) => {
		t.component = e;
		let r = e.vnode.props;
		e.vnode = t, e.next = null, _i(e, t.props, r, n), Ai(e, t.children, n), Ke(), Cn(e), qe();
	}, de = (e, t, n, r, i, a, o, s, c = !1) => {
		let l = e && e.children, u = e ? e.shapeFlag : 0, d = t.children, { patchFlag: f, shapeFlag: m } = t;
		if (f > 0) {
			if (f & 128) {
				me(l, d, n, r, i, a, o, s, c);
				return;
			} else if (f & 256) {
				fe(l, d, n, r, i, a, o, s, c);
				return;
			}
		}
		m & 8 ? (u & 16 && ye(l, i, a), d !== l && p(n, d)) : u & 16 ? m & 16 ? me(l, d, n, r, i, a, o, s, c) : ye(l, i, a, !0) : (u & 8 && p(n, ""), m & 16 && ne(d, n, r, i, a, o, s, c));
	}, fe = (e, t, n, r, a, o, s, c, l) => {
		e ||= i, t ||= i;
		let u = e.length, d = t.length, f = Math.min(u, d), p;
		for (p = 0; p < f; p++) {
			let r = t[p] = l ? sa(t[p]) : oa(t[p]);
			v(e[p], r, n, null, a, o, s, c, l);
		}
		u > d ? ye(e, a, o, !0, !1, f) : ne(t, n, r, a, o, s, c, l, f);
	}, me = (e, t, n, r, a, o, s, c, l) => {
		let u = 0, d = t.length, f = e.length - 1, p = d - 1;
		for (; u <= f && u <= p;) {
			let r = e[u], i = t[u] = l ? sa(t[u]) : oa(t[u]);
			if (ea(r, i)) v(r, i, n, null, a, o, s, c, l);
			else break;
			u++;
		}
		for (; u <= f && u <= p;) {
			let r = e[f], i = t[p] = l ? sa(t[p]) : oa(t[p]);
			if (ea(r, i)) v(r, i, n, null, a, o, s, c, l);
			else break;
			f--, p--;
		}
		if (u > f) {
			if (u <= p) {
				let e = p + 1, i = e < d ? t[e].el : r;
				for (; u <= p;) v(null, t[u] = l ? sa(t[u]) : oa(t[u]), n, i, a, o, s, c, l), u++;
			}
		} else if (u > p) for (; u <= f;) ge(e[u], a, o, !0), u++;
		else {
			let m = u, h = u, g = /* @__PURE__ */ new Map();
			for (u = h; u <= p; u++) {
				let e = t[u] = l ? sa(t[u]) : oa(t[u]);
				e.key != null && g.set(e.key, u);
			}
			let _, y = 0, b = p - h + 1, x = !1, S = 0, C = Array(b);
			for (u = 0; u < b; u++) C[u] = 0;
			for (u = m; u <= f; u++) {
				let r = e[u];
				if (y >= b) {
					ge(r, a, o, !0);
					continue;
				}
				let i;
				if (r.key != null) i = g.get(r.key);
				else for (_ = h; _ <= p; _++) if (C[_ - h] === 0 && ea(r, t[_])) {
					i = _;
					break;
				}
				i === void 0 ? ge(r, a, o, !0) : (C[i - h] = u + 1, i >= S ? S = i : x = !0, v(r, t[i], n, null, a, o, s, c, l), y++);
			}
			let w = x ? Ri(C) : i;
			for (_ = w.length - 1, u = b - 1; u >= 0; u--) {
				let e = h + u, i = t[e], f = t[e + 1], p = e + 1 < d ? f.el || Vi(f) : r;
				C[u] === 0 ? v(null, i, n, p, a, o, s, c, l) : x && (_ < 0 || u !== w[_] ? he(i, n, p, 2) : _--);
			}
		}
	}, he = (e, t, n, r, i = null) => {
		let { el: a, type: c, transition: l, children: u, shapeFlag: d } = e;
		if (d & 6) {
			he(e.component.subTree, t, n, r);
			return;
		}
		if (d & 128) {
			e.suspense.move(t, n, r);
			return;
		}
		if (d & 64) {
			c.move(e, t, n, Ce);
			return;
		}
		if (c === V) {
			o(a, t, n);
			for (let e = 0; e < u.length; e++) he(u[e], t, n, r);
			o(e.anchor, t, n);
			return;
		}
		if (c === Gi) {
			S(e, t, n);
			return;
		}
		if (r !== 2 && d & 1 && l) if (r === 0) l.persisted && !a[Hn] ? o(a, t, n) : (l.beforeEnter(a), o(a, t, n), ji(() => l.enter(a), i));
		else {
			let { leave: r, delayLeave: i, afterLeave: c } = l, u = () => {
				e.ctx.isUnmounted ? s(a) : o(a, t, n);
			}, d = () => {
				let e = a._isLeaving || !!a[Hn];
				a._isLeaving && a[Hn](!0), l.persisted && !e ? u() : r(a, () => {
					u(), c && c();
				});
			};
			i ? i(a, u, d) : d();
		}
		else o(a, t, n);
	}, ge = (e, t, n, r = !1, i = !1) => {
		let { type: a, props: o, ref: s, children: c, dynamicChildren: l, shapeFlag: u, patchFlag: d, dirs: f, cacheIndex: p, memo: m } = e;
		if (d === -2 && (i = !1), s != null && (Ke(), sr(s, null, n, e, !0), qe()), p != null && (t.renderCache[p] = void 0), u & 256) {
			t.ctx.deactivate(e);
			return;
		}
		let h = u & 1 && f, g = !lr(e), _;
		if (g && (_ = o && o.onVnodeBeforeUnmount) && ua(_, t, e), u & 6) O(e.component, n, r);
		else {
			if (u & 128) {
				e.suspense.unmount(n, r);
				return;
			}
			h && jn(e, null, t, "beforeUnmount"), u & 64 ? e.type.remove(e, t, n, Ce, r) : l && !l.hasOnce && (a !== V || d > 0 && d & 64) ? ye(l, t, n, !1, !0) : (a === V && d & 384 || !i && u & 16) && ye(c, t, n), r && _e(e);
		}
		let v = m != null && p == null;
		(g && (_ = o && o.onVnodeUnmounted) || h || v) && ji(() => {
			_ && ua(_, t, e), h && jn(e, null, t, "unmounted"), v && (e.el = null);
		}, n);
	}, _e = (e) => {
		let { type: t, el: n, anchor: r, transition: i } = e;
		if (t === V) {
			ve(n, r);
			return;
		}
		if (t === Gi) {
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
	}, ve = (e, t) => {
		let n;
		for (; e !== t;) n = h(e), s(e), e = n;
		s(t);
	}, O = (e, t, n) => {
		let { bum: r, scope: i, job: a, subTree: o, um: s, m: c, a: l } = e;
		Bi(c), Bi(l), r && ce(r), i.stop(), a && (a.flags |= 8, ge(o, e, t, n)), s && ji(s, t), ji(() => {
			e.isUnmounted = !0;
		}, t);
	}, ye = (e, t, n, r = !1, i = !1, a = 0) => {
		for (let o = a; o < e.length; o++) ge(e[o], t, n, r, i);
	}, be = (e) => {
		if (e.shapeFlag & 6) return be(e.component.subTree);
		if (e.shapeFlag & 128) return e.suspense.next();
		let t = h(e.anchor || e.el), n = t && t[Bn];
		return n ? h(n) : t;
	}, xe = !1, Se = (e, t, n) => {
		let r;
		e == null ? t._vnode && (ge(t._vnode, null, null, !0), r = t._vnode.component) : v(t._vnode || null, e, t, null, null, null, n), t._vnode = e, xe ||= (xe = !0, Cn(r), wn(), !1);
	}, Ce = {
		p: v,
		um: ge,
		m: he,
		r: _e,
		mt: se,
		mc: ne,
		pc: de,
		pbc: E,
		n: be,
		o: e
	}, we, Te;
	return t && ([we, Te] = t(Ce)), {
		render: Se,
		hydrate: we,
		createApp: $r(Se, we)
	};
}
function Pi({ type: e, props: t }, n) {
	return n === "svg" && e === "foreignObject" || n === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : n;
}
function Fi({ effect: e, job: t }, n) {
	n ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function Ii(e, t) {
	return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function Li(e, t, n = !1) {
	let r = e.children, i = t.children;
	if (p(r) && p(i)) for (let e = 0; e < r.length; e++) {
		let t = r[e], a = i[e];
		a.shapeFlag & 1 && !a.dynamicChildren && ((a.patchFlag <= 0 || a.patchFlag === 32) && (a = i[e] = sa(i[e]), a.el = t.el), !n && a.patchFlag !== -2 && Li(t, a)), a.type === Wi && (a.patchFlag === -1 && (a = i[e] = sa(a)), a.el = t.el), a.type === H && !a.el && (a.el = t.el);
	}
}
function Ri(e) {
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
function zi(e) {
	let t = e.subTree.component;
	if (t) return t.asyncDep && !t.asyncResolved ? t : zi(t);
}
function Bi(e) {
	if (e) for (let t = 0; t < e.length; t++) e[t].flags |= 8;
}
function Vi(e) {
	if (e.placeholder) return e.placeholder;
	let t = e.component;
	return t ? Vi(t.subTree) : null;
}
var Hi = (e) => e.__isSuspense;
function Ui(e, t) {
	t && t.pendingBranch ? p(e) ? t.effects.push(...e) : t.effects.push(e) : Sn(e);
}
var V = /* @__PURE__ */ Symbol.for("v-fgt"), Wi = /* @__PURE__ */ Symbol.for("v-txt"), H = /* @__PURE__ */ Symbol.for("v-cmt"), Gi = /* @__PURE__ */ Symbol.for("v-stc"), Ki = [], qi = null;
function U(e = !1) {
	Ki.push(qi = e ? null : []);
}
function Ji() {
	Ki.pop(), qi = Ki[Ki.length - 1] || null;
}
var Yi = 1;
function Xi(e, t = !1) {
	Yi += e, e < 0 && qi && t && (qi.hasOnce = !0);
}
function Zi(e) {
	return e.dynamicChildren = Yi > 0 ? qi || i : null, Ji(), Yi > 0 && qi && qi.push(e), e;
}
function W(e, t, n, r, i, a) {
	return Zi(G(e, t, n, r, i, a, !0));
}
function Qi(e, t, n, r, i) {
	return Zi(K(e, t, n, r, i, !0));
}
function $i(e) {
	return e ? e.__v_isVNode === !0 : !1;
}
function ea(e, t) {
	return e.type === t.type && e.key === t.key;
}
var ta = ({ key: e }) => e ?? null, na = ({ ref: e, ref_key: t, ref_for: n }) => (typeof e == "number" && (e = "" + e), e == null ? null : v(e) || /* @__PURE__ */ P(e) || _(e) ? {
	i: Dn,
	r: e,
	k: t,
	f: !!n
} : e);
function G(e, t = null, n = null, r = 0, i = null, a = e === V ? 0 : 1, o = !1, s = !1) {
	let c = {
		__v_isVNode: !0,
		__v_skip: !0,
		type: e,
		props: t,
		key: t && ta(t),
		ref: t && na(t),
		scopeId: On,
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
		ctx: Dn
	};
	return s ? (ca(c, n), a & 128 && e.normalize(c)) : n && (c.shapeFlag |= v(n) ? 8 : 16), Yi > 0 && !o && qi && (c.patchFlag > 0 || a & 6) && c.patchFlag !== 32 && qi.push(c), c;
}
var K = ra;
function ra(e, t = null, n = null, r = 0, i = null, a = !1) {
	if ((!e || e === Or) && (e = H), $i(e)) {
		let r = aa(e, t, !0);
		return n && ca(r, n), Yi > 0 && !a && qi && (r.shapeFlag & 6 ? qi[qi.indexOf(e)] = r : qi.push(r)), r.patchFlag = -2, r;
	}
	if (ja(e) && (e = e.__vccOpts), t) {
		t = ia(t);
		let { class: e, style: n } = t;
		e && !v(e) && (t.class = O(e)), b(n) && (/* @__PURE__ */ Wt(n) && !p(n) && (n = l({}, n)), t.style = me(n));
	}
	let o = v(e) ? 1 : Hi(e) ? 128 : Vn(e) ? 64 : b(e) ? 4 : _(e) ? 2 : 0;
	return G(e, t, n, r, i, o, a, !0);
}
function ia(e) {
	return e ? /* @__PURE__ */ Wt(e) || hi(e) ? l({}, e) : e : null;
}
function aa(e, t, n = !1, r = !1) {
	let { props: i, ref: a, patchFlag: o, children: s, transition: c } = e, l = t ? la(i || {}, t) : i, u = {
		__v_isVNode: !0,
		__v_skip: !0,
		type: e.type,
		props: l,
		key: l && ta(l),
		ref: t && t.ref ? n && a ? p(a) ? a.concat(na(t)) : [a, na(t)] : na(t) : a,
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
		ssContent: e.ssContent && aa(e.ssContent),
		ssFallback: e.ssFallback && aa(e.ssFallback),
		placeholder: e.placeholder,
		el: e.el,
		anchor: e.anchor,
		ctx: e.ctx,
		ce: e.ce
	};
	return c && r && tr(u, c.clone(u)), u;
}
function q(e = " ", t = 0) {
	return K(Wi, null, e, t);
}
function J(e = "", t = !1) {
	return t ? (U(), Qi(H, null, e)) : K(H, null, e);
}
function oa(e) {
	return e == null || typeof e == "boolean" ? K(H) : p(e) ? K(V, null, e.slice()) : $i(e) ? sa(e) : K(Wi, null, String(e));
}
function sa(e) {
	return e.el === null && e.patchFlag !== -1 || e.memo ? e : aa(e);
}
function ca(e, t) {
	let n = 0, { shapeFlag: r } = e;
	if (t == null) t = null;
	else if (p(t)) n = 16;
	else if (typeof t == "object") if (r & 65) {
		let n = t.default;
		n && (n._c && (n._d = !1), ca(e, n()), n._c && (n._d = !0));
		return;
	} else {
		n = 32;
		let r = t._;
		!r && !hi(t) ? t._ctx = Dn : r === 3 && Dn && (Dn.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
	}
	else _(t) ? (t = {
		default: t,
		_ctx: Dn
	}, n = 32) : (t = String(t), r & 64 ? (n = 16, t = [q(t)]) : n = 8);
	e.children = t, e.shapeFlag |= n;
}
function la(...e) {
	let t = {};
	for (let n = 0; n < e.length; n++) {
		let r = e[n];
		for (let e in r) if (e === "class") t.class !== r.class && (t.class = O([t.class, r.class]));
		else if (e === "style") t.style = me([t.style, r.style]);
		else if (s(e)) {
			let n = t[e], i = r[e];
			i && n !== i && !(p(n) && n.includes(i)) ? t[e] = n ? [].concat(n, i) : i : i == null && n == null && !c(e) && (t[e] = i);
		} else e !== "" && (t[e] = r[e]);
	}
	return t;
}
function ua(e, t, n, r = null) {
	ln(e, t, 7, [n, r]);
}
var da = Zr(), fa = 0;
function pa(e, t, n) {
	let i = e.type, a = (t ? t.appContext : e.appContext) || da, o = {
		uid: fa++,
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
		scope: new Oe(!0),
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
		propsOptions: xi(i, a),
		emitsOptions: ii(i, a),
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
	return o.ctx = { _: o }, o.root = t ? t.root : o, o.emit = ni.bind(null, o), e.ce && e.ce(o), o;
}
var Y = null, ma = () => Y || Dn, ha, ga;
{
	let e = pe(), t = (t, n) => {
		let r;
		return (r = e[t]) || (r = e[t] = []), r.push(n), (e) => {
			r.length > 1 ? r.forEach((t) => t(e)) : r[0](e);
		};
	};
	ha = t("__VUE_INSTANCE_SETTERS__", (e) => Y = e), ga = t("__VUE_SSR_SETTERS__", (e) => ba = e);
}
var _a = (e) => {
	let t = Y;
	return ha(e), e.scope.on(), () => {
		e.scope.off(), ha(t);
	};
}, va = () => {
	Y && Y.scope.off(), ha(null);
};
function ya(e) {
	return e.vnode.shapeFlag & 4;
}
var ba = !1;
function xa(e, t = !1, n = !1) {
	t && ga(t);
	let { props: r, children: i } = e.vnode, a = ya(e);
	gi(e, r, a, t), ki(e, i, n || t);
	let o = a ? Sa(e, t) : void 0;
	return t && ga(!1), o;
}
function Sa(e, t) {
	let n = e.type;
	e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, Fr);
	let { setup: r } = n;
	if (r) {
		Ke();
		let n = e.setupContext = r.length > 1 ? Oa(e) : null, i = _a(e), a = cn(r, e, 0, [e.props, n]), o = x(a);
		if (qe(), i(), (o || e.sp) && !lr(e) && ir(e), o) {
			if (a.then(va, va), t) return a.then((n) => {
				Ca(e, n, t);
			}).catch((t) => {
				un(t, e, 0);
			});
			e.asyncDep = a;
		} else Ca(e, a, t);
	} else Ea(e, t);
}
function Ca(e, t, n) {
	_(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : b(t) && (e.setupState = Qt(t)), Ea(e, n);
}
var wa, Ta;
function Ea(e, t, n) {
	let r = e.type;
	if (!e.render) {
		if (!t && wa && !r.render) {
			let t = r.template || Hr(e).template;
			if (t) {
				let { isCustomElement: n, compilerOptions: i } = e.appContext.config, { delimiters: a, compilerOptions: o } = r;
				r.render = wa(t, l(l({
					isCustomElement: n,
					delimiters: a
				}, i), o));
			}
		}
		e.render = r.render || a, Ta && Ta(e);
	}
	{
		let t = _a(e);
		Ke();
		try {
			Rr(e);
		} finally {
			qe(), t();
		}
	}
}
var Da = { get(e, t) {
	return M(e, "get", ""), e[t];
} };
function Oa(e) {
	return {
		attrs: new Proxy(e.attrs, Da),
		slots: e.slots,
		emit: e.emit,
		expose: (t) => {
			e.exposed = t || {};
		}
	};
}
function ka(e) {
	return e.exposed ? e.exposeProxy ||= new Proxy(Qt(Gt(e.exposed)), {
		get(t, n) {
			if (n in t) return t[n];
			if (n in Nr) return Nr[n](e);
		},
		has(e, t) {
			return t in e || t in Nr;
		}
	}) : e.proxy;
}
function Aa(e, t = !0) {
	return _(e) ? e.displayName || e.name : e.name || t && e.__name;
}
function ja(e) {
	return _(e) && "__vccOpts" in e;
}
var X = (e, t) => /* @__PURE__ */ en(e, t, ba);
function Ma(e, t, n) {
	try {
		Xi(-1);
		let r = arguments.length;
		return r === 2 ? b(t) && !p(t) ? $i(t) ? K(e, null, [t]) : K(e, t) : K(e, null, t) : (r > 3 ? n = Array.prototype.slice.call(arguments, 2) : r === 3 && $i(n) && (n = [n]), K(e, t, n));
	} finally {
		Xi(1);
	}
}
var Na = "3.5.38", Pa = void 0, Fa = typeof window < "u" && window.trustedTypes;
if (Fa) try {
	Pa = /* @__PURE__ */ Fa.createPolicy("vue", { createHTML: (e) => e });
} catch {}
var Ia = Pa ? (e) => Pa.createHTML(e) : (e) => e, La = "http://www.w3.org/2000/svg", Ra = "http://www.w3.org/1998/Math/MathML", za = typeof document < "u" ? document : null, Ba = za && /* @__PURE__ */ za.createElement("template"), Va = {
	insert: (e, t, n) => {
		t.insertBefore(e, n || null);
	},
	remove: (e) => {
		let t = e.parentNode;
		t && t.removeChild(e);
	},
	createElement: (e, t, n, r) => {
		let i = t === "svg" ? za.createElementNS(La, e) : t === "mathml" ? za.createElementNS(Ra, e) : n ? za.createElement(e, { is: n }) : za.createElement(e);
		return e === "select" && r && r.multiple != null && i.setAttribute("multiple", r.multiple), i;
	},
	createText: (e) => za.createTextNode(e),
	createComment: (e) => za.createComment(e),
	setText: (e, t) => {
		e.nodeValue = t;
	},
	setElementText: (e, t) => {
		e.textContent = t;
	},
	parentNode: (e) => e.parentNode,
	nextSibling: (e) => e.nextSibling,
	querySelector: (e) => za.querySelector(e),
	setScopeId(e, t) {
		e.setAttribute(t, "");
	},
	insertStaticContent(e, t, n, r, i, a) {
		let o = n ? n.previousSibling : t.lastChild;
		if (i && (i === a || i.nextSibling)) for (; t.insertBefore(i.cloneNode(!0), n), !(i === a || !(i = i.nextSibling)););
		else {
			Ba.innerHTML = Ia(r === "svg" ? `<svg>${e}</svg>` : r === "mathml" ? `<math>${e}</math>` : e);
			let i = Ba.content;
			if (r === "svg" || r === "mathml") {
				let e = i.firstChild;
				for (; e.firstChild;) i.appendChild(e.firstChild);
				i.removeChild(e);
			}
			t.insertBefore(i, n);
		}
		return [o ? o.nextSibling : t.firstChild, n ? n.previousSibling : t.lastChild];
	}
}, Ha = "transition", Ua = "animation", Wa = /* @__PURE__ */ Symbol("_vtc"), Ga = {
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
}, Ka = /* @__PURE__ */ l({}, Kn, Ga), qa = /* @__PURE__ */ ((e) => (e.displayName = "Transition", e.props = Ka, e))((e, { slots: t }) => Ma(Xn, Xa(e), t)), Ja = (e, t = []) => {
	p(e) ? e.forEach((e) => e(...t)) : e && e(...t);
}, Ya = (e) => e ? p(e) ? e.some((e) => e.length > 1) : e.length > 1 : !1;
function Xa(e) {
	let t = {};
	for (let n in e) n in Ga || (t[n] = e[n]);
	if (e.css === !1) return t;
	let { name: n = "v", type: r, duration: i, enterFromClass: a = `${n}-enter-from`, enterActiveClass: o = `${n}-enter-active`, enterToClass: s = `${n}-enter-to`, appearFromClass: c = a, appearActiveClass: u = o, appearToClass: d = s, leaveFromClass: f = `${n}-leave-from`, leaveActiveClass: p = `${n}-leave-active`, leaveToClass: m = `${n}-leave-to` } = e, h = Za(i), g = h && h[0], _ = h && h[1], { onBeforeEnter: v, onEnter: y, onEnterCancelled: b, onLeave: x, onLeaveCancelled: S, onBeforeAppear: C = v, onAppear: w = y, onAppearCancelled: T = b } = t, ee = (e, t, n, r) => {
		e._enterCancelled = r, eo(e, t ? d : s), eo(e, t ? u : o), n && n();
	}, te = (e, t) => {
		e._isLeaving = !1, eo(e, f), eo(e, m), eo(e, p), t && t();
	}, ne = (e) => (t, n) => {
		let i = e ? w : y, o = () => ee(t, e, n);
		Ja(i, [t, o]), to(() => {
			eo(t, e ? c : a), $a(t, e ? d : s), Ya(i) || ro(t, r, g, o);
		});
	};
	return l(t, {
		onBeforeEnter(e) {
			Ja(v, [e]), $a(e, a), $a(e, o);
		},
		onBeforeAppear(e) {
			Ja(C, [e]), $a(e, c), $a(e, u);
		},
		onEnter: ne(!1),
		onAppear: ne(!0),
		onLeave(e, t) {
			e._isLeaving = !0;
			let n = () => te(e, t);
			$a(e, f), e._enterCancelled ? ($a(e, p), so(e)) : (so(e), $a(e, p)), to(() => {
				e._isLeaving && (eo(e, f), $a(e, m), Ya(x) || ro(e, r, _, n));
			}), Ja(x, [e, n]);
		},
		onEnterCancelled(e) {
			ee(e, !1, void 0, !0), Ja(b, [e]);
		},
		onAppearCancelled(e) {
			ee(e, !0, void 0, !0), Ja(T, [e]);
		},
		onLeaveCancelled(e) {
			te(e), Ja(S, [e]);
		}
	});
}
function Za(e) {
	if (e == null) return null;
	if (b(e)) return [Qa(e.enter), Qa(e.leave)];
	{
		let t = Qa(e);
		return [t, t];
	}
}
function Qa(e) {
	return de(e);
}
function $a(e, t) {
	t.split(/\s+/).forEach((t) => t && e.classList.add(t)), (e[Wa] || (e[Wa] = /* @__PURE__ */ new Set())).add(t);
}
function eo(e, t) {
	t.split(/\s+/).forEach((t) => t && e.classList.remove(t));
	let n = e[Wa];
	n && (n.delete(t), n.size || (e[Wa] = void 0));
}
function to(e) {
	requestAnimationFrame(() => {
		requestAnimationFrame(e);
	});
}
var no = 0;
function ro(e, t, n, r) {
	let i = e._endId = ++no, a = () => {
		i === e._endId && r();
	};
	if (n != null) return setTimeout(a, n);
	let { type: o, timeout: s, propCount: c } = io(e, t);
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
function io(e, t) {
	let n = window.getComputedStyle(e), r = (e) => (n[e] || "").split(", "), i = r(`${Ha}Delay`), a = r(`${Ha}Duration`), o = ao(i, a), s = r(`${Ua}Delay`), c = r(`${Ua}Duration`), l = ao(s, c), u = null, d = 0, f = 0;
	t === Ha ? o > 0 && (u = Ha, d = o, f = a.length) : t === Ua ? l > 0 && (u = Ua, d = l, f = c.length) : (d = Math.max(o, l), u = d > 0 ? o > l ? Ha : Ua : null, f = u ? u === Ha ? a.length : c.length : 0);
	let p = u === Ha && /\b(?:transform|all)(?:,|$)/.test(r(`${Ha}Property`).toString());
	return {
		type: u,
		timeout: d,
		propCount: f,
		hasTransform: p
	};
}
function ao(e, t) {
	for (; e.length < t.length;) e = e.concat(e);
	return Math.max(...t.map((t, n) => oo(t) + oo(e[n])));
}
function oo(e) {
	return e === "auto" ? 0 : Number(e.slice(0, -1).replace(",", ".")) * 1e3;
}
function so(e) {
	return (e ? e.ownerDocument : document).body.offsetHeight;
}
function co(e, t, n) {
	let r = e[Wa];
	r && (t = (t ? [t, ...r] : [...r]).join(" ")), t == null ? e.removeAttribute("class") : n ? e.setAttribute("class", t) : e.className = t;
}
var lo = /* @__PURE__ */ Symbol("_vod"), uo = /* @__PURE__ */ Symbol("_vsh"), fo = /* @__PURE__ */ Symbol(""), po = /(?:^|;)\s*display\s*:/;
function mo(e, t, n) {
	let r = e.style, i = v(n), a = !1;
	if (n && !i) {
		if (t) if (v(t)) for (let e of t.split(";")) {
			let t = e.slice(0, e.indexOf(":")).trim();
			n[t] ?? go(r, t, "");
		}
		else for (let e in t) n[e] ?? go(r, e, "");
		for (let i in n) {
			i === "display" && (a = !0);
			let o = n[i];
			o == null ? go(r, i, "") : bo(e, i, !v(t) && t ? t[i] : void 0, o) || go(r, i, o);
		}
	} else if (i) {
		if (t !== n) {
			let e = r[fo];
			e && (n += ";" + e), r.cssText = n, a = po.test(n);
		}
	} else t && e.removeAttribute("style");
	lo in e && (e[lo] = a ? r.display : "", e[uo] && (r.display = "none"));
}
var ho = /\s*!important$/;
function go(e, t, n) {
	if (p(n)) n.forEach((n) => go(e, t, n));
	else if (n ??= "", t.startsWith("--")) e.setProperty(t, n);
	else {
		let r = yo(e, t);
		ho.test(n) ? e.setProperty(ae(r), n.replace(ho, ""), "important") : e[r] = n;
	}
}
var _o = [
	"Webkit",
	"Moz",
	"ms"
], vo = {};
function yo(e, t) {
	let n = vo[t];
	if (n) return n;
	let r = E(t);
	if (r !== "filter" && r in e) return vo[t] = r;
	r = oe(r);
	for (let n = 0; n < _o.length; n++) {
		let i = _o[n] + r;
		if (i in e) return vo[t] = i;
	}
	return t;
}
function bo(e, t, n, r) {
	return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && v(r) && n === r;
}
var xo = "http://www.w3.org/1999/xlink";
function So(e, t, n, r, i, a = be(t)) {
	r && t.startsWith("xlink:") ? n == null ? e.removeAttributeNS(xo, t.slice(6, t.length)) : e.setAttributeNS(xo, t, n) : n == null || a && !xe(n) ? e.removeAttribute(t) : e.setAttribute(t, a ? "" : y(n) ? String(n) : n);
}
function Co(e, t, n, r, i) {
	if (t === "innerHTML" || t === "textContent") {
		n != null && (e[t] = t === "innerHTML" ? Ia(n) : n);
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
		r === "boolean" ? n = xe(n) : n == null && r === "string" ? (n = "", o = !0) : r === "number" && (n = 0, o = !0);
	}
	try {
		e[t] = n;
	} catch {}
	o && e.removeAttribute(i || t);
}
function wo(e, t, n, r) {
	e.addEventListener(t, n, r);
}
function To(e, t, n, r) {
	e.removeEventListener(t, n, r);
}
var Eo = /* @__PURE__ */ Symbol("_vei");
function Do(e, t, n, r, i = null) {
	let a = e[Eo] || (e[Eo] = {}), o = a[t];
	if (r && o) o.value = r;
	else {
		let [n, s] = ko(t);
		r ? wo(e, n, a[t] = No(r, i), s) : o && (To(e, n, o, s), a[t] = void 0);
	}
}
var Oo = /(?:Once|Passive|Capture)$/;
function ko(e) {
	let t;
	if (Oo.test(e)) {
		t = {};
		let n;
		for (; n = e.match(Oo);) e = e.slice(0, e.length - n[0].length), t[n[0].toLowerCase()] = !0;
	}
	return [e[2] === ":" ? e.slice(3) : ae(e.slice(2)), t];
}
var Ao = 0, jo = /* @__PURE__ */ Promise.resolve(), Mo = () => Ao ||= (jo.then(() => Ao = 0), Date.now());
function No(e, t) {
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
				e && ln(e, t, 5, a);
			}
		} else ln(r, t, 5, [e]);
	};
	return n.value = e, n.attached = Mo(), n;
}
var Po = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, Fo = (e, t, n, r, i, a) => {
	let o = i === "svg";
	t === "class" ? co(e, r, o) : t === "style" ? mo(e, n, r) : s(t) ? c(t) || Do(e, t, n, r, a) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : Io(e, t, r, o)) ? (Co(e, t, r), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && So(e, t, r, o, a, t !== "value")) : e._isVueCE && (Lo(e, t) || e._def.__asyncLoader && (/[A-Z]/.test(t) || !v(r))) ? Co(e, E(t), r, a, t) : (t === "true-value" ? e._trueValue = r : t === "false-value" && (e._falseValue = r), So(e, t, r, o));
};
function Io(e, t, n, r) {
	if (r) return !!(t === "innerHTML" || t === "textContent" || t in e && Po(t) && _(n));
	if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA") return !1;
	if (t === "width" || t === "height") {
		let t = e.tagName;
		if (t === "IMG" || t === "VIDEO" || t === "CANVAS" || t === "SOURCE") return !1;
	}
	return Po(t) && v(n) ? !1 : t in e;
}
function Lo(e, t) {
	let n = e._def.props;
	if (!n) return !1;
	let r = E(t);
	return Array.isArray(n) ? n.some((e) => E(e) === r) : Object.keys(n).some((e) => E(e) === r);
}
var Ro = (e) => {
	let t = e.props["onUpdate:modelValue"] || !1;
	return p(t) ? (e) => ce(t, e) : t;
};
function zo(e) {
	e.target.composing = !0;
}
function Bo(e) {
	let t = e.target;
	t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
var Vo = /* @__PURE__ */ Symbol("_assign");
function Ho(e, t, n) {
	return t && (e = e.trim()), n && (e = ue(e)), e;
}
var Z = {
	created(e, { modifiers: { lazy: t, trim: n, number: r } }, i) {
		e[Vo] = Ro(i);
		let a = r || i.props && i.props.type === "number";
		wo(e, t ? "change" : "input", (t) => {
			t.target.composing || e[Vo](Ho(e.value, n, a));
		}), (n || a) && wo(e, "change", () => {
			e.value = Ho(e.value, n, a);
		}), t || (wo(e, "compositionstart", zo), wo(e, "compositionend", Bo), wo(e, "change", Bo));
	},
	mounted(e, { value: t }) {
		e.value = t ?? "";
	},
	beforeUpdate(e, { value: t, oldValue: n, modifiers: { lazy: r, trim: i, number: a } }, o) {
		if (e[Vo] = Ro(o), e.composing) return;
		let s = (a || e.type === "number") && !/^0\d/.test(e.value) ? ue(e.value) : e.value, c = t ?? "";
		if (s === c) return;
		let l = e.getRootNode();
		(l instanceof Document || l instanceof ShadowRoot) && l.activeElement === e && e.type !== "range" && (r && t === n || i && e.value.trim() === c) || (e.value = c);
	}
}, Uo = {
	deep: !0,
	created(e, t, n) {
		e[Vo] = Ro(n), wo(e, "change", () => {
			let t = e._modelValue, n = Jo(e), r = e.checked, i = e[Vo];
			if (p(t)) {
				let e = we(t, n), a = e !== -1;
				if (r && !a) i(t.concat(n));
				else if (!r && a) {
					let n = [...t];
					n.splice(e, 1), i(n);
				}
			} else if (h(t)) {
				let e = new Set(t);
				r ? e.add(n) : e.delete(n), i(e);
			} else i(Yo(e, r));
		});
	},
	mounted: Wo,
	beforeUpdate(e, t, n) {
		e[Vo] = Ro(n), Wo(e, t, n);
	}
};
function Wo(e, { value: t, oldValue: n }, r) {
	e._modelValue = t;
	let i;
	if (p(t)) i = we(t, r.props.value) > -1;
	else if (h(t)) i = t.has(r.props.value);
	else {
		if (t === n) return;
		i = Ce(t, Yo(e, !0));
	}
	e.checked !== i && (e.checked = i);
}
var Go = {
	created(e, { value: t }, n) {
		e.checked = Ce(t, n.props.value), e[Vo] = Ro(n), wo(e, "change", () => {
			e[Vo](Jo(e));
		});
	},
	beforeUpdate(e, { value: t, oldValue: n }, r) {
		e[Vo] = Ro(r), t !== n && (e.checked = Ce(t, r.props.value));
	}
}, Ko = {
	deep: !0,
	created(e, { value: t, modifiers: { number: n } }, r) {
		let i = h(t);
		wo(e, "change", () => {
			let t = Array.prototype.filter.call(e.options, (e) => e.selected).map((e) => n ? ue(Jo(e)) : Jo(e));
			e[Vo](e.multiple ? i ? new Set(t) : t : t[0]), e._assigning = !0, vn(() => {
				e._assigning = !1;
			});
		}), e[Vo] = Ro(r);
	},
	mounted(e, { value: t }) {
		qo(e, t);
	},
	beforeUpdate(e, t, n) {
		e[Vo] = Ro(n);
	},
	updated(e, { value: t }) {
		e._assigning || qo(e, t);
	}
};
function qo(e, t) {
	let n = e.multiple, r = p(t);
	if (!(n && !r && !h(t))) {
		for (let i = 0, a = e.options.length; i < a; i++) {
			let a = e.options[i], o = Jo(a);
			if (n) if (r) {
				let e = typeof o;
				e === "string" || e === "number" ? a.selected = t.some((e) => String(e) === String(o)) : a.selected = we(t, o) > -1;
			} else a.selected = t.has(o);
			else if (Ce(Jo(a), t)) {
				e.selectedIndex !== i && (e.selectedIndex = i);
				return;
			}
		}
		!n && e.selectedIndex !== -1 && (e.selectedIndex = -1);
	}
}
function Jo(e) {
	return "_value" in e ? e._value : e.value;
}
function Yo(e, t) {
	let n = t ? "_trueValue" : "_falseValue";
	return n in e ? e[n] : t;
}
var Xo = {
	created(e, t, n) {
		Qo(e, t, n, null, "created");
	},
	mounted(e, t, n) {
		Qo(e, t, n, null, "mounted");
	},
	beforeUpdate(e, t, n, r) {
		Qo(e, t, n, r, "beforeUpdate");
	},
	updated(e, t, n, r) {
		Qo(e, t, n, r, "updated");
	}
};
function Zo(e, t) {
	switch (e) {
		case "SELECT": return Ko;
		case "TEXTAREA": return Z;
		default: switch (t) {
			case "checkbox": return Uo;
			case "radio": return Go;
			default: return Z;
		}
	}
}
function Qo(e, t, n, r, i) {
	let a = Zo(e.tagName, n.props && n.props.type)[i];
	a && a(e, t, n, r);
}
var $o = [
	"ctrl",
	"shift",
	"alt",
	"meta"
], es = {
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
	exact: (e, t) => $o.some((n) => e[`${n}Key`] && !t.includes(n))
}, Q = (e, t) => {
	if (!e) return e;
	let n = e._withMods ||= {}, r = t.join(".");
	return n[r] || (n[r] = ((n, ...r) => {
		for (let e = 0; e < t.length; e++) {
			let r = es[t[e]];
			if (r && r(n, t)) return;
		}
		return e(n, ...r);
	}));
}, ts = /* @__PURE__ */ l({ patchProp: Fo }, Va), ns;
function rs() {
	return ns ||= Mi(ts);
}
var is = ((...e) => {
	let t = rs().createApp(...e), { mount: n } = t;
	return t.mount = (e) => {
		let r = os(e);
		if (!r) return;
		let i = t._component;
		!_(i) && !i.render && !i.template && (i.template = r.innerHTML), r.nodeType === 1 && (r.textContent = "");
		let a = n(r, !1, as(r));
		return r instanceof Element && (r.removeAttribute("v-cloak"), r.setAttribute("data-v-app", "")), a;
	}, t;
});
function as(e) {
	if (e instanceof SVGElement) return "svg";
	if (typeof MathMLElement == "function" && e instanceof MathMLElement) return "mathml";
}
function os(e) {
	return v(e) ? document.querySelector(e) : e;
}
//#endregion
//#region node_modules/lucide-vue-next/dist/esm/shared/src/utils/hasA11yProp.js
var ss = (e) => {
	for (let t in e) if (t.startsWith("aria-") || t === "role" || t === "title") return !0;
	return !1;
}, cs = (e) => e === "", ls = (...e) => e.filter((e, t, n) => !!e && e.trim() !== "" && n.indexOf(e) === t).join(" ").trim(), us = (e) => e.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase(), ds = (e) => e.replace(/^([A-Z])|[\s-_]+(\w)/g, (e, t, n) => n ? n.toUpperCase() : t.toLowerCase()), fs = (e) => {
	let t = ds(e);
	return t.charAt(0).toUpperCase() + t.slice(1);
}, ps = {
	xmlns: "http://www.w3.org/2000/svg",
	width: 24,
	height: 24,
	viewBox: "0 0 24 24",
	fill: "none",
	stroke: "currentColor",
	"stroke-width": 2,
	"stroke-linecap": "round",
	"stroke-linejoin": "round"
}, ms = ({ name: e, iconNode: t, absoluteStrokeWidth: n, "absolute-stroke-width": r, strokeWidth: i, "stroke-width": a, size: o = ps.width, color: s = ps.stroke, ...c }, { slots: l }) => Ma("svg", {
	...ps,
	...c,
	width: o,
	height: o,
	stroke: s,
	"stroke-width": cs(n) || cs(r) || n === !0 || r === !0 ? Number(i || a || ps["stroke-width"]) * 24 / Number(o) : i || a || ps["stroke-width"],
	class: ls("lucide", c.class, ...e ? [`lucide-${us(fs(e))}-icon`, `lucide-${us(e)}`] : ["lucide-icon"]),
	...!l.default && !ss(c) && { "aria-hidden": "true" }
}, [...t.map((e) => Ma(...e)), ...l.default ? [l.default()] : []]), $ = (e, t) => (n, { slots: r, attrs: i }) => Ma(ms, {
	...i,
	...n,
	iconNode: t,
	name: e
}, r), hs = $("activity", [["path", {
	d: "M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2",
	key: "169zse"
}]]), gs = $("arrow-down-to-line", [
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
]), _s = $("arrow-down", [["path", {
	d: "M12 5v14",
	key: "s699le"
}], ["path", {
	d: "m19 12-7 7-7-7",
	key: "1idqje"
}]]), vs = $("arrow-left-right", [
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
]), ys = $("arrow-up-right", [["path", {
	d: "M7 7h10v10",
	key: "1tivn9"
}], ["path", {
	d: "M7 17 17 7",
	key: "1vkiza"
}]]), bs = $("arrow-up", [["path", {
	d: "m5 12 7-7 7 7",
	key: "hav0vg"
}], ["path", {
	d: "M12 19V5",
	key: "x0mq9r"
}]]), xs = $("check", [["path", {
	d: "M20 6 9 17l-5-5",
	key: "1gmf2c"
}]]), Ss = $("chevron-down", [["path", {
	d: "m6 9 6 6 6-6",
	key: "qrunsl"
}]]), Cs = $("chevron-right", [["path", {
	d: "m9 18 6-6-6-6",
	key: "mthhwq"
}]]), ws = $("chevron-up", [["path", {
	d: "m18 15-6-6-6 6",
	key: "153udz"
}]]), Ts = $("chevrons-up-down", [["path", {
	d: "m7 15 5 5 5-5",
	key: "1hf1tw"
}], ["path", {
	d: "m7 9 5-5 5 5",
	key: "sgt6xg"
}]]), Es = $("clock", [["circle", {
	cx: "12",
	cy: "12",
	r: "10",
	key: "1mglay"
}], ["path", {
	d: "M12 6v6l4 2",
	key: "mmk7yg"
}]]), Ds = $("database", [
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
]), Os = $("download", [
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
]), ks = $("eye-off", [
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
]), As = $("eye", [["path", {
	d: "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0",
	key: "1nclc0"
}], ["circle", {
	cx: "12",
	cy: "12",
	r: "3",
	key: "1v7zrd"
}]]), js = $("file-down", [
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
]), Ms = $("file-up", [
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
]), Ns = $("gauge", [["path", {
	d: "m12 14 4-4",
	key: "9kzdfg"
}], ["path", {
	d: "M3.34 19a10 10 0 1 1 17.32 0",
	key: "19p75a"
}]]), Ps = $("globe", [
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
]), Fs = $("house", [["path", {
	d: "M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8",
	key: "5wwlr5"
}], ["path", {
	d: "M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
	key: "r6nss1"
}]]), Is = $("link", [["path", {
	d: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71",
	key: "1cjeqo"
}], ["path", {
	d: "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71",
	key: "19qd67"
}]]), Ls = $("monitor", [
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
]), Rs = $("network", [
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
]), zs = $("pause", [["rect", {
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
}]]), Bs = $("play", [["path", {
	d: "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z",
	key: "10ikf1"
}]]), Vs = $("plus", [["path", {
	d: "M5 12h14",
	key: "1ays0h"
}], ["path", {
	d: "M12 5v14",
	key: "s699le"
}]]), Hs = $("power", [["path", {
	d: "M12 2v10",
	key: "mnfbl"
}], ["path", {
	d: "M18.4 6.6a9 9 0 1 1-12.77.04",
	key: "obofu9"
}]]), Us = $("radio", [
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
]), Ws = $("refresh-cw", [
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
]), Gs = $("search", [["path", {
	d: "m21 21-4.34-4.34",
	key: "14j7rj"
}], ["circle", {
	cx: "11",
	cy: "11",
	r: "8",
	key: "4ej97u"
}]]), Ks = $("settings-2", [
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
]), qs = $("shield-check", [["path", {
	d: "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",
	key: "oel41y"
}], ["path", {
	d: "m9 12 2 2 4-4",
	key: "dzmm74"
}]]), Js = $("shield-off", [
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
]), Ys = $("sliders-horizontal", [
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
]), Xs = $("undo-2", [["path", {
	d: "M9 14 4 9l5-5",
	key: "102s5s"
}], ["path", {
	d: "M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11",
	key: "f3b9sd"
}]]), Zs = $("x", [["path", {
	d: "M18 6 6 18",
	key: "1bl5f8"
}], ["path", {
	d: "m6 6 12 12",
	key: "d8bk6v"
}]]), Qs = $("zap", [["path", {
	d: "M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z",
	key: "1xq2db"
}]]), $s = (t) => t == null ? "—" : `${e(t)}/s`, ec = (e) => ({
	active: "下载中",
	waiting: "等待中",
	paused: "已暂停",
	complete: "已完成",
	removed: "已取消",
	error: "下载失败",
	recoverable: "待恢复"
})[e] || "等待中", tc = (e) => e ? new Date(e).toLocaleString("zh-CN", {
	month: "2-digit",
	day: "2-digit",
	hour: "2-digit",
	minute: "2-digit"
}) : "刚刚", nc = (e) => e === "DIRECT" ? "直接连接" : e === "REJECT" ? "阻止连接" : e || "尚未选择线路";
function rc(e, t, n = 0) {
	let r = e?.[t];
	return !r || !Array.isArray(r.all) || !r.now || n > 4 ? t : rc(e, r.now, n + 1);
}
function ic(e) {
	let t = e?.proxies;
	if (!t) return "";
	let n = Object.entries(t).filter(([, e]) => Array.isArray(e.all) && e.now), r = n.find(([e]) => e === "GLOBAL") || n.find(([, e]) => e.type === "Selector") || n[0];
	return r ? rc(t, r[1].now) : "";
}
function ac(e) {
	let n = /* @__PURE__ */ Jt(null), r = /* @__PURE__ */ F(null), i = /* @__PURE__ */ F([]), a = X(() => n.value?.downloads || []), o = /* @__PURE__ */ F(null), s = /* @__PURE__ */ F(""), c = /* @__PURE__ */ F(""), l = /* @__PURE__ */ F(""), u = /* @__PURE__ */ F(""), d = /* @__PURE__ */ F(!1), f = !1, p, m = async (t, n = {}) => {
		if (f || e.signal?.aborted) throw Error("页面已关闭");
		let r = await e.rpc(`network-exploration.${t}`, n);
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
	let x = X(() => (n.value?.transactions || []).find((e) => e.request?.kind === "proxy" && e.status === "applied")), S = X(() => !!(n.value?.accelerator?.running && o.value?.enabled === 1 && o.value?.server === `127.0.0.1:${n.value.accelerator.port}`)), C = X(() => o.value !== null);
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
	async function T(e) {
		n.value?.proxy?.running && await y("proxy.mode", { mode: e }, "连接模式已更新") && await g();
	}
	async function ee(e, t) {
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
	let re = t.subscribe({
		rpc: e.rpc,
		signal: e.signal,
		visible: () => e.visible !== !1,
		update(e, t) {
			f || (n.value = e, u.value = t || "");
		}
	}), E = e.onVisibilityChange?.(() => t.visibilityChanged()) || (() => {});
	In(() => n.value?.proxy?.running, () => {
		g();
	}, { immediate: !0 }), vr(async () => {
		await Promise.all([_(), e.compact ? Promise.resolve() : h("interfaces").then((e) => {
			e && (i.value = e.interfaces || []);
		})]);
	}), xr(() => {
		f = !0, re(), E();
	});
	async function ie() {
		await Promise.all([
			t.refresh(),
			_(),
			g()
		]);
	}
	return /* @__PURE__ */ Lt({
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
		refresh: ie,
		loadProxy: g,
		loadTasks: v,
		loadSystemProxy: _,
		toggleProxy: b,
		toggleAcceleration: w,
		setMode: T,
		selectNode: ee,
		optimizeNode: te,
		diagnose: ne
	});
}
//#endregion
//#region ../src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue
var oc = { class: "nx-home" }, sc = {
	class: "nx-stat-bar",
	"data-stat-bar": "",
	"aria-label": "实时网络数据"
}, cc = {
	class: "nx-stat",
	"data-stat": "download"
}, lc = {
	class: "nx-stat",
	"data-stat": "upload"
}, uc = {
	class: "nx-stat",
	"data-stat": "total"
}, dc = {
	class: "nx-stat",
	"data-stat": "delay"
}, fc = { class: "nx-home-grid" }, pc = { class: "nx-quick-head" }, mc = { class: "nx-quick-icon" }, hc = { class: "nx-quick-main" }, gc = { class: "nx-quick-actions" }, _c = ["aria-pressed", "disabled"], vc = { class: "nx-quick-head" }, yc = { class: "nx-quick-icon" }, bc = { class: "nx-quick-main" }, xc = { class: "nx-quick-actions" }, Sc = ["aria-pressed", "disabled"], Cc = { class: "nx-quick-head" }, wc = { class: "nx-quick-icon" }, Tc = { class: "nx-quick-main" }, Ec = { class: "nx-quick-actions nx-quick-actions--stack" }, Dc = ["disabled"], Oc = {
	__name: "HomeView",
	props: { session: Object },
	emits: ["navigate"],
	setup(t, { emit: n }) {
		let r = t, i = n, a = /* @__PURE__ */ F(""), o = X(() => !!r.session.accelerated), s = X(() => Number(r.session.state?.traffic?.download || 0)), c = X(() => Number(r.session.state?.traffic?.upload || 0)), l = X(() => Number(r.session.state?.traffic?.received || 0) + Number(r.session.state?.traffic?.sent || 0)), u = X(() => !!r.session.state?.proxy?.config_saved), d = X(() => !!r.session.state?.proxy?.running), f = X(() => ic(r.session.proxy)), p = X(() => f.value ? nc(f.value) : d.value ? "正在读取线路" : "尚未连接"), m = X(() => Number(r.session.proxy?.proxies?.[f.value]?.history?.at(-1)?.delay || 0)), h = X(() => r.session.tasks.filter((e) => !["complete", "removed"].includes(e.status)).length), g = X(() => r.session.tasks.reduce((e, t) => e + (Number(t.downloadSpeed) || 0), 0)), _ = X(() => r.session.busy === "proxy.start" ? "正在准备线路…" : r.session.busy === "accelerator.start" ? "正在准备…" : r.session.busy === "system.apply" ? "正在开启…" : o.value ? "停止加速" : "一键加速"), v = X(() => r.session.busy === "proxy.start" ? "连接中…" : r.session.busy === "proxy.stop" ? "关闭中…" : d.value ? "关闭代理" : u.value ? "开启代理" : "添加订阅");
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
		return (n, r) => (U(), W("div", oc, [G("section", sc, [
			G("div", cc, [G("span", null, [K(I(_s), { size: 13 }), r[4] ||= q("实时下载", -1)]), G("strong", null, k(I($s)(s.value)), 1)]),
			G("div", lc, [G("span", null, [K(I(bs), { size: 13 }), r[5] ||= q("实时上传", -1)]), G("strong", null, k(I($s)(c.value)), 1)]),
			G("div", uc, [G("span", null, [K(I(Ds), { size: 13 }), r[6] ||= q("累计流量", -1)]), G("strong", null, k(I(e)(l.value)), 1)]),
			G("div", dc, [G("span", null, [K(I(Ns), { size: 13 }), r[7] ||= q("线路延迟", -1)]), G("strong", null, k(m.value ? `${m.value} ms` : "—"), 1)])
		]), G("div", fc, [
			G("section", {
				class: O(["nx-quick-card", { "is-on": o.value }]),
				"data-home-block": "acceleration"
			}, [
				G("header", pc, [
					G("span", mc, [K(I(Qs), { size: 19 })]),
					r[8] ||= G("div", { class: "nx-quick-title" }, [G("h2", null, "加速"), G("p", null, "本机加速")], -1),
					G("span", { class: O(["nx-quick-state", { "is-live": o.value }]) }, k(o.value ? "运行中" : "未加速"), 3)
				]),
				G("div", hc, [G("strong", null, k(o.value ? "常用站点直连" : "无需订阅"), 1), G("p", null, k(o.value ? d.value ? "本机直连 · 线路兜底已就绪" : "DoH 选路，失败时按系统解析" : "有订阅会自动准备线路兜底"), 1)]),
				G("div", gc, [G("button", {
					class: O(["nx-button", o.value ? "nx-secondary" : "nx-primary"]),
					"aria-pressed": o.value,
					disabled: !!t.session.busy || !t.session.systemProxyReady,
					"data-acceleration": "",
					onClick: y
				}, [K(I(Hs), { size: 15 }), q(k(_.value), 1)], 10, _c), G("button", {
					class: "nx-button nx-quiet nx-quick-link",
					"data-home-open": "overview",
					onClick: r[0] ||= (e) => i("navigate", "overview")
				}, [r[9] ||= q(" 详情", -1), K(I(ys), { size: 13 })])])
			], 2),
			G("section", {
				class: O(["nx-quick-card", { "is-on": d.value }]),
				"data-home-block": "proxy"
			}, [
				G("header", vc, [
					G("span", yc, [K(I(Ps), { size: 19 })]),
					r[10] ||= G("div", { class: "nx-quick-title" }, [G("h2", null, "代理"), G("p", null, "订阅线路")], -1),
					G("span", { class: O(["nx-quick-state", { "is-live": d.value }]) }, k(d.value ? "已连接" : u.value ? "待连接" : "未配置"), 3)
				]),
				G("div", bc, [G("strong", null, k(p.value), 1), G("p", null, k(d.value && m.value ? `${m.value} ms · 当前线路` : u.value ? "开启后加载订阅里的节点" : "先去代理页添加订阅"), 1)]),
				G("div", xc, [G("button", {
					class: O(["nx-button", d.value ? "nx-secondary" : "nx-primary"]),
					"aria-pressed": d.value,
					disabled: !!t.session.busy,
					"data-home-proxy": "",
					onClick: b
				}, [K(I(Hs), { size: 15 }), q(k(v.value), 1)], 10, Sc), G("button", {
					class: "nx-button nx-quiet nx-quick-link",
					"data-home-open": "proxy",
					onClick: r[1] ||= (e) => i("navigate", "proxy")
				}, [r[11] ||= q(" 选线路", -1), K(I(ys), { size: 13 })])])
			], 2),
			G("section", {
				class: O(["nx-quick-card", { "is-on": h.value > 0 }]),
				"data-home-block": "transfer"
			}, [
				G("header", Cc, [
					G("span", wc, [K(I(Os), { size: 19 })]),
					r[12] ||= G("div", { class: "nx-quick-title" }, [G("h2", null, "下载"), G("p", null, "快速取回文件")], -1),
					G("span", { class: O(["nx-quick-state", { "is-live": h.value > 0 }]) }, k(h.value ? "进行中" : "空闲"), 3)
				]),
				G("div", Tc, [G("strong", null, k(h.value ? `${h.value} 个任务` : "没有进行中的下载"), 1), G("p", null, k(h.value ? `${I($s)(g.value)} 总速度` : "粘贴链接即可开始，默认 8 连接"), 1)]),
				G("div", Ec, [G("form", {
					class: "nx-home-download",
					"data-home-download": "",
					onSubmit: Q(x, ["prevent"])
				}, [R(G("input", {
					"onUpdate:modelValue": r[2] ||= (e) => a.value = e,
					class: "nx-input",
					"aria-label": "下载链接",
					placeholder: "粘贴下载链接",
					required: ""
				}, null, 512), [[Z, a.value]]), G("button", {
					class: "nx-button nx-primary",
					disabled: !!t.session.busy || !a.value.trim(),
					"aria-label": "开始下载"
				}, [K(I(Os), { size: 15 })], 8, Dc)], 32), G("button", {
					class: "nx-button nx-quiet nx-quick-link",
					"data-home-open": "transfer",
					onClick: r[3] ||= (e) => i("navigate", "transfer")
				}, [r[13] ||= q(" 打开下载页", -1), K(I(ys), { size: 13 })])])
			], 2)
		])]));
	}
}, kc = {
	class: "nx-panel nx-speed",
	"data-network-chart": ""
}, Ac = { class: "nx-panel-heading" }, jc = { class: "nx-speed-values" }, Mc = { class: "nx-plot" }, Nc = {
	key: 0,
	viewBox: "0 0 640 164",
	preserveAspectRatio: "none",
	role: "img",
	"aria-label": "实时下载和上传速度趋势"
}, Pc = ["d"], Fc = ["d"], Ic = ["d"], Lc = ["d"], Rc = {
	key: 1,
	class: "nx-chart-wait"
}, zc = { class: "nx-chart-axis" }, Bc = { key: 0 }, Vc = {
	__name: "SpeedChart",
	props: {
		history: { default: () => [] },
		traffic: { default: null },
		compact: Boolean
	},
	setup(t) {
		let n = t, r = `nx-speed-${rr().replace(/:/g, "")}`, i = X(() => Math.max(1024, ...n.history.flatMap((e) => [Number(e.download || 0), Number(e.upload || 0)])));
		function a(e) {
			let t = n.history;
			return t.length < 2 ? "" : t.map((n, r) => `${r ? "L" : "M"}${(r / (t.length - 1) * 640).toFixed(2)},${(154 - Number(n[e] || 0) / i.value * 138).toFixed(2)}`).join(" ");
		}
		let o = X(() => a("download")), s = X(() => a("upload")), c = X(() => o.value ? `${o.value} L640,164 L0,164 Z` : "");
		return (n, a) => (U(), W("section", kc, [
			G("div", Ac, [G("h2", null, [K(I(hs), { size: 17 }), a[0] ||= q("实时网速", -1)]), a[1] ||= G("span", { class: "nx-subtle" }, "系统接口", -1)]),
			G("div", jc, [G("span", null, [
				K(I(_s), { size: 17 }),
				G("strong", null, k(I($s)(t.traffic?.download)), 1),
				a[2] ||= G("small", null, "下载", -1)
			]), G("span", null, [
				K(I(bs), { size: 17 }),
				G("strong", null, k(I($s)(t.traffic?.upload)), 1),
				a[3] ||= G("small", null, "上传", -1)
			])]),
			G("div", Mc, [t.history.length > 1 ? (U(), W("svg", Nc, [
				G("defs", null, [G("linearGradient", {
					id: r,
					x1: "0",
					x2: "0",
					y1: "0",
					y2: "1"
				}, [...a[4] ||= [G("stop", {
					offset: "0%",
					"stop-color": "currentColor",
					"stop-opacity": ".18"
				}, null, -1), G("stop", {
					offset: "100%",
					"stop-color": "currentColor",
					"stop-opacity": "0"
				}, null, -1)]])]),
				(U(), W(V, null, z([
					26,
					72,
					118,
					163
				], (e) => G("path", {
					key: e,
					d: `M0,${e}H640`,
					class: "nx-chart-grid"
				}, null, 8, Pc)), 64)),
				G("path", {
					d: c.value,
					style: me({ fill: `url(#${r})` }),
					class: "nx-chart-area"
				}, null, 12, Fc),
				G("path", {
					d: s.value,
					class: "nx-chart-upload"
				}, null, 8, Ic),
				G("path", {
					d: o.value,
					class: "nx-chart-download"
				}, null, 8, Lc)
			])) : (U(), W("div", Rc, [
				K(I(hs), { size: 22 }),
				a[5] ||= G("span", null, "正在收集网速变化", -1),
				a[6] ||= G("small", null, "新的采样会自动显示在这里", -1)
			]))]),
			G("div", zc, [
				G("span", null, k(t.history.length > 1 ? "较早" : "等待采样"), 1),
				t.history.length > 1 ? (U(), W("span", Bc, "最高 " + k(I(e)(i.value)) + "/s", 1)) : J("", !0),
				a[7] ||= G("span", null, "现在", -1)
			])
		]));
	}
}, Hc = { class: "nx-accel-page" }, Uc = { class: "nx-accel-orb" }, Wc = { class: "nx-accel-copy" }, Gc = ["aria-pressed", "disabled"], Kc = { class: "nx-accel-grid" }, qc = { class: "nx-panel nx-accel-facts" }, Jc = { class: "nx-panel-heading" }, Yc = { class: "nx-fact" }, Xc = { class: "nx-panel nx-site-check" }, Zc = { class: "nx-panel-heading" }, Qc = ["disabled"], $c = { class: "nx-site-shortcuts" }, el = ["onClick"], tl = {
	key: 0,
	class: "nx-panel nx-recent"
}, nl = { class: "nx-section-heading" }, rl = {
	__name: "DashboardView",
	props: { session: Object },
	emits: ["navigate", "diagnostic"],
	setup(e, { emit: t }) {
		let n = e, r = t, i = /* @__PURE__ */ F("github.com"), a = X(() => !!n.session.accelerated);
		async function o() {
			await n.session.toggleAcceleration();
		}
		async function s() {
			let e = await n.session.diagnose(i.value);
			e?.report && r("diagnostic", e.report);
		}
		return (t, n) => (U(), W("div", Hc, [
			G("section", { class: O(["nx-accel-control", { "is-on": a.value }]) }, [
				G("div", Uc, [K(I(Hs), {
					size: 24,
					"stroke-width": 1.7
				})]),
				G("div", Wc, [
					n[3] ||= G("span", { class: "nx-kicker" }, "LOCAL ACCELERATION", -1),
					G("h2", null, k(a.value ? "本机加速中" : "未加速"), 1),
					G("p", null, k(a.value ? "本机直连：命中 GitHub、Steam 等常用站点时用 DoH 选 IP。" : "不需要订阅。点一下，用 DoH 选路直连 GitHub、Steam 等常用站点。"), 1)
				]),
				G("button", {
					class: O(["nx-button nx-large", a.value ? "nx-secondary" : "nx-primary"]),
					"aria-pressed": a.value,
					disabled: !!e.session.busy || !e.session.systemProxyReady,
					"data-acceleration": "",
					onClick: o
				}, [K(I(Hs), { size: 17 }), q(k(e.session.busy === "proxy.start" ? "正在准备线路…" : e.session.busy === "accelerator.start" ? "正在准备…" : e.session.busy === "system.apply" ? "正在开启…" : a.value ? "停止加速" : "一键加速"), 1)], 10, Gc)
			], 2),
			G("div", Kc, [K(Vc, {
				history: e.session.state?.history || [],
				traffic: e.session.state?.traffic
			}, null, 8, ["history", "traffic"]), G("section", qc, [
				G("div", Jc, [G("h2", null, [K(I(qs), { size: 17 }), n[4] ||= q("运行方式", -1)])]),
				n[7] ||= G("div", { class: "nx-fact" }, [G("span", null, "加速方式"), G("strong", null, "DoH 选 IP 直连")], -1),
				n[8] ||= G("div", { class: "nx-fact" }, [G("span", null, "系统改动"), G("strong", null, "仅系统代理")], -1),
				n[9] ||= G("div", { class: "nx-fact" }, [G("span", null, "证书 / hosts"), G("strong", null, "不修改")], -1),
				G("div", Yc, [n[6] ||= G("span", null, "订阅线路", -1), G("button", {
					class: "nx-button nx-quiet nx-fact-link",
					onClick: n[0] ||= (e) => r("navigate", "proxy")
				}, [n[5] ||= q(" 去代理页管理", -1), K(I(ys), { size: 13 })])]),
				n[10] ||= G("p", { class: "nx-help" }, " 有订阅时会自动准备线路兜底，但不改系统代理；直连失败的域名会记住并优先走线路。 ", -1)
			])]),
			G("div", { class: O(["nx-accel-lower", { "nx-single": !e.session.state?.events?.length }]) }, [G("section", Xc, [
				G("div", Zc, [G("h2", null, [K(I(Is), { size: 17 }), n[11] ||= q("检查网站访问", -1)])]),
				G("form", {
					class: "nx-inline-form",
					onSubmit: Q(s, ["prevent"])
				}, [R(G("input", {
					"onUpdate:modelValue": n[1] ||= (e) => i.value = e,
					class: "nx-input",
					"aria-label": "要检查的网站",
					placeholder: "输入网址，例如 github.com",
					required: ""
				}, null, 512), [[Z, i.value]]), G("button", {
					class: "nx-button nx-secondary",
					disabled: !!e.session.busy
				}, [K(I(hs), { size: 15 }), q(k(e.session.busy === "diagnose" ? "检查中…" : "检查一下"), 1)], 8, Qc)], 32),
				G("div", $c, [n[12] ||= G("span", null, "常用网站", -1), (U(), W(V, null, z([
					"github.com",
					"huggingface.co",
					"google.com"
				], (e) => G("button", {
					key: e,
					class: "nx-button nx-quiet",
					onClick: (t) => i.value = e
				}, k(e), 9, el)), 64))])
			]), e.session.state?.events?.length ? (U(), W("section", tl, [G("div", nl, [n[14] ||= G("h2", null, "最近活动", -1), G("button", {
				class: "nx-button nx-quiet",
				onClick: n[2] ||= (e) => r("navigate", "advanced")
			}, [n[13] ||= q(" 查看记录", -1), K(I(ys), { size: 13 })])]), (U(!0), W(V, null, z([...e.session.state.events].reverse().slice(0, 3), (e, t) => (U(), W("div", {
				key: t,
				class: "nx-event"
			}, [
				K(I(xs), { size: 14 }),
				G("span", null, k(e.message), 1),
				G("time", null, k(I(tc)(e.time)), 1)
			]))), 128))])) : J("", !0)], 2)
		]));
	}
}, il = { class: "nx-panel nx-nodes" }, al = { class: "nx-panel-heading" }, ol = { class: "nx-node-head-actions" }, sl = ["disabled"], cl = ["disabled"], ll = {
	class: "nx-line-groups",
	role: "group",
	"aria-label": "线路分组"
}, ul = ["aria-pressed", "onClick"], dl = { class: "nx-subtle" }, fl = [
	"data-node",
	"aria-pressed",
	"disabled",
	"onClick"
], pl = { class: "nx-line-radio" }, ml = { class: "nx-line-name" }, hl = { class: "nx-line-ms" }, gl = [
	"disabled",
	"aria-label",
	"onClick"
], _l = {
	key: 1,
	class: "nx-empty nx-empty--small"
}, vl = {
	__name: "NodePicker",
	props: {
		session: Object,
		compact: Boolean
	},
	emits: ["import"],
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(""), r = /* @__PURE__ */ F(""), i = /* @__PURE__ */ F({}), a = X(() => {
			let e = Object.entries(t.session.proxy?.proxies || {}).filter(([, e]) => Array.isArray(e.all) && e.type === "Selector"), n = t.session.proxy?.mode === "global";
			return e.sort(([e], [t]) => Number(t === "GLOBAL") * (n ? 1 : -1) - Number(e === "GLOBAL") * (n ? 1 : -1));
		});
		In(a, (e) => {
			e.some(([e]) => e === n.value) || (n.value = e[0]?.[0] || "");
		}, { immediate: !0 });
		let o = X(() => a.value.find(([e]) => e === n.value)?.[1]), s = X(() => (o.value?.all || []).filter((e) => e.toLowerCase().includes(r.value.toLowerCase())));
		function c(e) {
			let n = i.value[e] ?? t.session.proxy?.proxies?.[e]?.history?.at(-1)?.delay;
			return Number(n) > 0 ? `${n} ms` : "未测速";
		}
		function l(e) {
			let n = i.value[e] ?? t.session.proxy?.proxies?.[e]?.history?.at(-1)?.delay;
			return Number(n) > 0 ? Number(n) : 0;
		}
		function u(e) {
			let t = l(e);
			return t ? Math.max(8, Math.round(100 - Math.min(100, t / 3))) : 8;
		}
		function d(e) {
			let t = l(e);
			return t ? t <= 90 ? "is-fast" : t <= 200 ? "is-mid" : "is-slow" : "is-unknown";
		}
		async function f(e) {
			let n = await t.session.run("proxy.delay", { name: e });
			n?.delay != null && (i.value[e] = n.delay);
		}
		async function p() {
			let e = await t.session.optimizeNode(n.value);
			if (e) for (let t of e.candidates || []) Number(t.delay) > 0 && (i.value[t.name] = t.delay);
		}
		return (t, i) => (U(), W("section", il, [
			G("div", al, [G("div", null, [i[5] ||= G("span", { class: "nx-kicker" }, "03 / 线路与测速", -1), G("h2", null, [K(I(Us), { size: 17 }), i[4] ||= q("选择线路", -1)])]), G("div", ol, [G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				"aria-label": "刷新线路",
				disabled: !!e.session.busy,
				onClick: i[0] ||= (t) => e.session.loadProxy()
			}, [K(I(Ws), { size: 15 })], 8, sl), G("button", {
				class: "nx-button nx-secondary nx-optimize",
				"data-optimize": "",
				disabled: !!e.session.busy || !s.value.length,
				onClick: p
			}, [K(I(Qs), { size: 13 }), q(k(e.session.busy === "proxy.optimize" ? "测速中…" : "选择最快"), 1)], 8, cl)])]),
			i[9] ||= G("p", { class: "nx-help" }, "点一行直接切换；右侧刷新键单独测速。", -1),
			a.value.length ? (U(), W(V, { key: 0 }, [
				G("div", ll, [(U(!0), W(V, null, z(a.value, ([e]) => (U(), W("button", {
					key: e,
					class: O(["nx-line-group", { "is-active": n.value === e }]),
					"aria-pressed": n.value === e,
					onClick: (t) => n.value = e
				}, [q(k(e) + " ", 1), G("span", null, k((a.value.length, "")), 1)], 10, ul))), 128)), G("span", dl, k(s.value.length) + " 条", 1)]),
				s.value.length > 8 ? R((U(), W("input", {
					key: 0,
					"onUpdate:modelValue": i[1] ||= (e) => r.value = e,
					class: "nx-input nx-node-search",
					placeholder: "搜索线路",
					"aria-label": "搜索线路"
				}, null, 512)), [[Z, r.value]]) : J("", !0),
				G("div", { class: O(["nx-line-list", { "nx-node-list--compact": e.compact }]) }, [(U(!0), W(V, null, z(s.value, (t) => (U(), W("div", {
					key: t,
					class: O(["nx-line-row", { "is-selected": o.value.now === t }])
				}, [G("button", {
					class: "nx-line-choice",
					"data-node": t,
					"aria-pressed": o.value.now === t,
					disabled: !!e.session.busy,
					onClick: (r) => e.session.selectNode(n.value, t)
				}, [
					G("span", pl, [o.value.now === t ? (U(), Qi(I(xs), {
						key: 0,
						size: 11
					})) : J("", !0)]),
					G("span", ml, k(t === "DIRECT" ? "直接连接" : t === "REJECT" ? "阻止连接" : t), 1),
					G("span", { class: O(["nx-line-meter", d(t)]) }, [G("i", { style: me({ width: `${u(t)}%` }) }, null, 4)], 2),
					G("span", hl, k(c(t)), 1)
				], 8, fl), e.compact ? J("", !0) : (U(), W("button", {
					key: 0,
					class: "nx-button nx-quiet nx-icon-button nx-line-refresh",
					disabled: !!e.session.busy,
					"aria-label": `测试 ${t} 的延迟`,
					onClick: (e) => f(t)
				}, [K(I(Ws), { size: 13 })], 8, gl))], 2))), 128))], 2),
				G("button", {
					class: "nx-button nx-quiet nx-add-profile",
					onClick: i[2] ||= (e) => t.$emit("import")
				}, [K(I(Vs), { size: 14 }), i[6] ||= q("添加或更新订阅 ", -1)])
			], 64)) : (U(), W("div", _l, [
				K(I(Us), { size: 24 }),
				G("strong", null, k(e.session.state?.proxy?.running ? "尚未找到可选线路" : "开启代理后可切换线路"), 1),
				i[8] ||= G("p", null, "添加订阅，使用你已有的代理节点。", -1),
				G("button", {
					class: "nx-button nx-secondary",
					onClick: i[3] ||= (e) => t.$emit("import")
				}, [K(I(Vs), { size: 14 }), i[7] ||= q("添加订阅 ", -1)])
			]))
		]));
	}
}, yl = {
	class: "nx-panel nx-import",
	"data-profile-import": ""
}, bl = { class: "nx-panel-heading" }, xl = { class: "nx-input-with-action" }, Sl = ["type"], Cl = ["aria-label"], wl = ["disabled"], Tl = {
	key: 0,
	class: "nx-help"
}, El = { class: "nx-import-options" }, Dl = ["disabled"], Ol = ["aria-expanded"], kl = ["disabled"], Al = {
	key: 2,
	class: "nx-help"
}, jl = {
	__name: "ImportProfile",
	props: {
		session: Object,
		autoStart: Boolean
	},
	emits: ["close"],
	setup(e, { emit: t }) {
		let n = e, r = t, i = /* @__PURE__ */ F(""), a = /* @__PURE__ */ F(!1), o = /* @__PURE__ */ F(null), s = /* @__PURE__ */ F(!1), c = /* @__PURE__ */ F("");
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
		return (t, n) => (U(), W("section", yl, [
			G("div", bl, [G("h2", null, [K(I(Is), { size: 17 }), n[8] ||= q("添加订阅", -1)]), G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				"aria-label": "收起订阅设置",
				onClick: n[0] ||= (e) => t.$emit("close")
			}, [K(I(Zs), { size: 16 })])]),
			n[10] ||= G("p", { class: "nx-help" }, "粘贴你的订阅链接。已有配置文件也可以直接导入。", -1),
			G("form", {
				class: "nx-inline-form",
				onSubmit: n[3] ||= Q((e) => l({ subscription: i.value.trim() }), ["prevent"])
			}, [G("label", xl, [R(G("input", {
				"onUpdate:modelValue": n[1] ||= (e) => i.value = e,
				type: a.value ? "text" : "password",
				class: "nx-input",
				required: "",
				placeholder: "https://…",
				"aria-label": "订阅链接",
				autocomplete: "off"
			}, null, 8, Sl), [[Xo, i.value]]), G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				type: "button",
				"aria-label": a.value ? "隐藏订阅链接" : "显示订阅链接",
				onClick: n[2] ||= (e) => a.value = !a.value
			}, [(U(), Qi(kr(a.value ? I(ks) : I(As)), { size: 16 }))], 8, Cl)]), G("button", {
				class: "nx-button nx-primary",
				disabled: !!e.session.busy || !i.value.trim()
			}, k(e.session.busy === "proxy.config" ? "正在下载…" : "保存订阅"), 9, wl)], 32),
			e.session.busy === "proxy.config" ? (U(), W("p", Tl, " 正在下载订阅。慢速订阅可能需要几十秒，请不要关闭页面。 ")) : J("", !0),
			G("div", El, [
				G("button", {
					class: "nx-button nx-quiet",
					disabled: !!e.session.busy,
					onClick: n[4] ||= (e) => o.value.click()
				}, [K(I(Ms), { size: 14 }), n[9] ||= q("导入配置文件", -1)], 8, Dl),
				G("button", {
					class: "nx-button nx-quiet",
					"aria-expanded": s.value,
					onClick: n[5] ||= (e) => s.value = !s.value
				}, k(s.value ? "收起文本配置" : "粘贴配置文本"), 9, Ol),
				G("input", {
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
				onSubmit: n[7] ||= Q((e) => l({ content: c.value }), ["prevent"])
			}, [R(G("textarea", {
				"onUpdate:modelValue": n[6] ||= (e) => c.value = e,
				class: "nx-input nx-code",
				rows: "7",
				"aria-label": "代理配置文本",
				placeholder: "粘贴 Mihomo / Clash YAML 配置",
				required: ""
			}, null, 512), [[Z, c.value]]), G("button", {
				class: "nx-button nx-secondary",
				disabled: !!e.session.busy
			}, " 保存配置 ", 8, kl)], 32)) : J("", !0),
			e.session.state?.proxy?.running ? (U(), W("p", Al, " 当前连接已开启。保存订阅或配置时会自动断开并重新连接，不需要手动关闭。 ")) : J("", !0)
		]));
	}
}, Ml = { class: "nx-view-stack" }, Nl = { class: "nx-section-heading" }, Pl = { class: "nx-proxy-top" }, Fl = { class: "nx-panel nx-subscribe-summary" }, Il = { class: "nx-subscribe-copy" }, Ll = { class: "nx-panel nx-proxy-connection" }, Rl = { class: "nx-proxy-connection-row" }, zl = { class: "nx-route-icon" }, Bl = { class: "nx-control-copy" }, Vl = ["aria-checked", "disabled"], Hl = {
	__name: "ProxyView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(!1), r = X(() => !!t.session.state?.proxy?.config_saved);
		return (t, i) => (U(), W("div", Ml, [
			G("div", Nl, [i[5] ||= G("div", null, [
				G("span", { class: "nx-kicker" }, "PROXY DESK"),
				G("h2", null, "订阅与线路"),
				G("p", null, "先有订阅，再选一条线路。")
			], -1), G("button", {
				class: "nx-button nx-secondary",
				onClick: i[0] ||= (e) => n.value = !n.value
			}, [K(I(Vs), { size: 15 }), q(k(r.value ? "更新订阅" : "添加订阅"), 1)])]),
			n.value ? (U(), Qi(jl, {
				key: 0,
				session: e.session,
				onClose: i[1] ||= (e) => n.value = !1
			}, null, 8, ["session"])) : J("", !0),
			G("div", Pl, [G("section", Fl, [
				i[6] ||= G("span", { class: "nx-kicker" }, "01 / 订阅", -1),
				G("div", Il, [G("h3", null, k(r.value ? "订阅已保存" : "还没有订阅"), 1), G("p", null, k(r.value ? "已使用当前 Windows 账户加密保存。更新订阅会自动重连。" : "粘贴服务商给你的 HTTPS 订阅链接，节点会自动出现。"), 1)]),
				G("button", {
					class: O(["nx-button", r.value ? "nx-quiet" : "nx-primary"]),
					onClick: i[2] ||= (e) => n.value = !0
				}, [K(I(Is), { size: 14 }), q(k(r.value ? "更新订阅" : "粘贴订阅链接"), 1)], 2)
			]), G("section", Ll, [i[8] ||= G("span", { class: "nx-kicker" }, "02 / 连接", -1), G("div", Rl, [
				G("span", zl, [K(I(Hs), { size: 18 })]),
				G("div", Bl, [G("strong", null, k(e.session.state?.proxy?.running ? "已连接" : "未连接"), 1), G("p", null, k(r.value ? e.session.state?.proxy?.running ? "节点已加载，可以在下面切换。" : "开启后加载订阅里的节点。" : "先保存订阅，才能启动代理。"), 1)]),
				G("button", {
					role: "switch",
					"aria-checked": !!e.session.state?.proxy?.running,
					"aria-label": "代理连接",
					class: "nx-switch",
					"data-proxy-switch": "",
					disabled: !!e.session.busy || !r.value,
					onClick: i[3] ||= (t) => e.session.toggleProxy()
				}, [...i[7] ||= [G("span", null, null, -1)]], 8, Vl)
			])])]),
			K(vl, {
				session: e.session,
				onImport: i[4] ||= (e) => n.value = !0
			}, null, 8, ["session"])
		]));
	}
}, Ul = { class: "nx-view-stack" }, Wl = { class: "nx-download-stats" }, Gl = { class: "nx-panel-heading" }, Kl = { class: "nx-inline-form" }, ql = ["disabled"], Jl = { class: "nx-download-options" }, Yl = ["value"], Xl = ["aria-expanded"], Zl = {
	key: 0,
	class: "nx-form-grid"
}, Ql = ["disabled"], $l = { class: "nx-list-toolbar" }, eu = { class: "nx-filter-tabs" }, tu = { class: "nx-panel nx-task-list" }, nu = ["data-task"], ru = { class: "nx-file-icon" }, iu = { class: "nx-download-body" }, au = { class: "nx-task-title" }, ou = ["aria-valuenow", "aria-label"], su = { class: "nx-task-meta" }, cu = { key: 0 }, lu = { key: 1 }, uu = { key: 2 }, du = { class: "nx-task-controls" }, fu = ["disabled", "onClick"], pu = ["disabled", "onClick"], mu = [
	"aria-label",
	"aria-expanded",
	"onClick"
], hu = {
	key: 0,
	class: "nx-task-details"
}, gu = { class: "nx-subtle" }, _u = { class: "nx-actions" }, vu = { class: "nx-small-select" }, yu = ["onChange"], bu = ["disabled", "onClick"], xu = ["disabled", "onClick"], Su = ["disabled", "onClick"], Cu = {
	key: 0,
	class: "nx-empty"
}, wu = {
	__name: "TransferView",
	props: { session: Object },
	setup(t) {
		let n = t, r = /* @__PURE__ */ F("active"), i = /* @__PURE__ */ F(""), a = /* @__PURE__ */ F(""), o = /* @__PURE__ */ F(""), s = /* @__PURE__ */ F(""), c = /* @__PURE__ */ F("auto"), l = /* @__PURE__ */ F(!1), u = /* @__PURE__ */ F(8), d = /* @__PURE__ */ F(0), f = /* @__PURE__ */ F(!1), p = /* @__PURE__ */ F(""), m = X(() => n.session.tasks.reduce((e, t) => e + (Number(t.downloadSpeed) || 0), 0)), h = X(() => n.session.tasks.map((e) => ({
			...n.session.state?.downloads?.find((t) => t.gid === e.gid),
			...e
		})).filter((e) => r.value === "all" || (r.value === "complete" ? e.status === "complete" : !["complete", "removed"].includes(e.status)))), g = X(() => n.session.tasks.filter((e) => !["complete", "removed"].includes(e.status)).length), _ = X(() => n.session.tasks.filter((e) => e.status === "complete").length);
		function v(e) {
			return Math.min(100, Number(e.completedLength || 0) / Math.max(1, Number(e.totalLength || 0)) * 100);
		}
		function y(e) {
			let t = (Number(e.totalLength || 0) - Number(e.completedLength || 0)) / Math.max(0, Number(e.downloadSpeed || 0));
			return Number.isFinite(t) && t > 0 ? t < 60 ? `约 ${Math.ceil(t)} 秒` : `约 ${Math.ceil(t / 60)} 分钟` : "等待传输";
		}
		async function b() {
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
		function x(e) {
			f.value = !1;
			let t = (e.dataTransfer?.getData("text/uri-list") || e.dataTransfer?.getData("text/plain") || "").split(/\r?\n/).map((e) => e.trim()).find(Boolean);
			if (!t || !/^https?:\/\//i.test(t)) {
				n.session.error = "请拖入一个 HTTP 或 HTTPS 下载链接";
				return;
			}
			i.value = t, n.session.notice = "链接已填入，点“开始下载”";
		}
		async function S(e, t) {
			e.status === "recoverable" && t === "resume" && !await n.session.run("transfer.recover", {}) || (await n.session.run("transfer.action", {
				gid: e.gid,
				action: t
			}), await n.session.loadTasks());
		}
		async function C(e, t) {
			await n.session.run("transfer.action", {
				gid: e.gid,
				action: "limit",
				bytes_per_second: Number(t)
			}, "下载限速已更新");
		}
		async function w(e) {
			let t = await n.session.run("transfer.verify", { gid: e.gid });
			t && (t.verified === !1 ? n.session.error = "文件与预期校验值不一致，请核对下载来源" : n.session.notice = t.verified === !0 ? "文件校验通过" : `文件校验值：${t.sha256}`);
		}
		return (n, T) => (U(), W("div", Ul, [
			T[39] ||= G("div", { class: "nx-section-heading" }, [G("div", null, [G("h2", null, "下载"), G("p", null, "粘贴链接或把链接拖进来，点“开始下载”。")])], -1),
			G("div", Wl, [
				G("div", null, [T[15] ||= G("span", null, "进行中", -1), G("strong", null, k(g.value), 1)]),
				G("div", null, [T[16] ||= G("span", null, "已完成", -1), G("strong", null, k(_.value), 1)]),
				G("div", null, [T[17] ||= G("span", null, "总速度", -1), G("strong", null, k(I($s)(m.value)), 1)])
			]),
			G("form", {
				class: O(["nx-panel nx-download-composer", { "is-dragging": f.value }]),
				"data-download-drop": "",
				onSubmit: Q(b, ["prevent"]),
				onDragover: T[8] ||= Q(() => {}, ["prevent"]),
				onDragenter: T[9] ||= Q((e) => f.value = !0, ["prevent"]),
				onDragleave: T[10] ||= (e) => f.value = !1,
				onDrop: Q(x, ["prevent"])
			}, [
				G("div", Gl, [G("h2", null, [K(I(Os), { size: 17 }), T[18] ||= q("新建下载", -1)]), T[19] ||= G("span", { class: "nx-subtle" }, "支持 HTTP / HTTPS", -1)]),
				G("div", Kl, [R(G("input", {
					"onUpdate:modelValue": T[0] ||= (e) => i.value = e,
					name: "url",
					class: "nx-input",
					required: "",
					placeholder: "粘贴下载链接，或把链接拖到这里",
					"aria-label": "下载链接"
				}, null, 512), [[Z, i.value]]), G("button", {
					class: "nx-button nx-primary",
					disabled: !!t.session.busy || !i.value.trim()
				}, " 开始下载 ", 8, ql)]),
				G("div", Jl, [G("label", null, [T[20] ||= G("span", null, "并行数量", -1), R(G("select", {
					"onUpdate:modelValue": T[1] ||= (e) => u.value = e,
					"aria-label": "并行数量"
				}, [(U(), W(V, null, z([
					1,
					2,
					4,
					8,
					16
				], (e) => G("option", {
					key: e,
					value: e
				}, k(e), 9, Yl)), 64))], 512), [[
					Ko,
					u.value,
					void 0,
					{ number: !0 }
				]])]), G("label", null, [T[22] ||= G("span", null, "下载限速", -1), R(G("select", {
					"onUpdate:modelValue": T[2] ||= (e) => d.value = e,
					"aria-label": "下载限速"
				}, [...T[21] ||= [
					G("option", { value: 0 }, "不限速", -1),
					G("option", { value: 1048576 }, "1 MB/s", -1),
					G("option", { value: 5242880 }, "5 MB/s", -1),
					G("option", { value: 10485760 }, "10 MB/s", -1)
				]], 512), [[
					Ko,
					d.value,
					void 0,
					{ number: !0 }
				]])])]),
				G("button", {
					type: "button",
					class: "nx-button nx-quiet nx-options-button",
					"aria-expanded": l.value,
					onClick: T[3] ||= (e) => l.value = !l.value
				}, [T[23] ||= q(" 更多选项", -1), K(I(Ss), { size: 13 })], 8, Xl),
				l.value ? (U(), W("div", Zl, [
					G("label", null, [T[24] ||= G("span", null, "文件名", -1), R(G("input", {
						"onUpdate:modelValue": T[4] ||= (e) => a.value = e,
						class: "nx-input",
						placeholder: "自动使用链接中的文件名"
					}, null, 512), [[Z, a.value]])]),
					G("label", null, [T[25] ||= G("span", null, "保存目录", -1), R(G("input", {
						"onUpdate:modelValue": T[5] ||= (e) => o.value = e,
						class: "nx-input",
						placeholder: "留空使用默认下载目录"
					}, null, 512), [[Z, o.value]])]),
					G("label", null, [T[26] ||= G("span", null, "文件校验值（可选）", -1), R(G("input", {
						"onUpdate:modelValue": T[6] ||= (e) => s.value = e,
						class: "nx-input",
						placeholder: "SHA-256"
					}, null, 512), [[Z, s.value]])]),
					G("label", null, [T[29] ||= G("span", null, "下载线路", -1), R(G("select", {
						"onUpdate:modelValue": T[7] ||= (e) => c.value = e,
						"aria-label": "下载线路"
					}, [
						T[27] ||= G("option", { value: "auto" }, "自动（跟随加速）", -1),
						T[28] ||= G("option", { value: "direct" }, "直接连接", -1),
						G("option", {
							value: "proxy",
							disabled: !t.session.state?.proxy?.running
						}, " 当前代理 ", 8, Ql)
					], 512), [[Ko, c.value]])])
				])) : J("", !0)
			], 34),
			G("div", $l, [G("div", eu, [
				G("button", {
					class: O({ active: r.value === "active" }),
					onClick: T[11] ||= (e) => r.value = "active"
				}, [T[30] ||= q(" 进行中", -1), G("span", null, k(g.value), 1)], 2),
				G("button", {
					class: O({ active: r.value === "complete" }),
					onClick: T[12] ||= (e) => r.value = "complete"
				}, [T[31] ||= q(" 已完成", -1), G("span", null, k(_.value), 1)], 2),
				G("button", {
					class: O({ active: r.value === "all" }),
					onClick: T[13] ||= (e) => r.value = "all"
				}, " 全部 ", 2)
			]), G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				"aria-label": "刷新下载列表",
				onClick: T[14] ||= (e) => t.session.loadTasks()
			}, [K(I(Ws), { size: 15 })])]),
			G("section", tu, [(U(!0), W(V, null, z(h.value, (n) => (U(), W("article", {
				key: n.gid,
				class: "nx-download-row",
				"data-task": n.gid
			}, [
				G("div", ru, [K(I(js), {
					size: 22,
					"stroke-width": 1.5
				})]),
				G("div", iu, [
					G("div", au, [G("strong", null, k(n.filename || "未命名下载"), 1), G("span", { class: O({ "nx-state-error": n.status === "error" }) }, k(I(ec)(n.status)), 3)]),
					G("div", {
						class: "nx-progress-track",
						role: "progressbar",
						"aria-valuenow": Math.round(v(n)),
						"aria-valuemin": "0",
						"aria-valuemax": "100",
						"aria-label": `${n.filename || "下载"}的进度`
					}, [G("span", { style: me({ width: `${v(n)}%` }) }, null, 4)], 8, ou),
					G("div", su, [G("span", null, [
						q(k(I(e)(n.completedLength)), 1),
						T[32] ||= G("span", { class: "nx-meta-divider" }, " / ", -1),
						q(k(I(e)(n.totalLength)), 1)
					]), n.status === "active" ? (U(), W("span", cu, [
						q(k(I($s)(n.downloadSpeed)), 1),
						T[33] ||= G("span", { class: "nx-meta-divider" }, "·", -1),
						q(k(y(n)), 1)
					])) : n.status === "complete" ? (U(), W("span", lu, "已保存到本地")) : n.status === "error" ? (U(), W("span", uu, "链接可能失效，或下载源暂时不可用")) : J("", !0)])
				]),
				G("div", du, [n.status === "active" || n.status === "waiting" ? (U(), W("button", {
					key: 0,
					class: "nx-button nx-secondary nx-icon-button",
					"aria-label": "暂停下载",
					"data-task-action": "pause",
					disabled: !!t.session.busy,
					onClick: (e) => S(n, "pause")
				}, [K(I(zs), { size: 15 })], 8, fu)) : ["paused", "recoverable"].includes(n.status) ? (U(), W("button", {
					key: 1,
					class: "nx-button nx-secondary nx-icon-button",
					"aria-label": "继续下载",
					"data-task-action": "resume",
					disabled: !!t.session.busy,
					onClick: (e) => S(n, "resume")
				}, [K(I(Bs), { size: 15 })], 8, pu)) : J("", !0), G("button", {
					class: "nx-button nx-quiet nx-icon-button",
					"aria-label": p.value === n.gid ? "收起下载详情" : "展开下载详情",
					"aria-expanded": p.value === n.gid,
					onClick: (e) => p.value = p.value === n.gid ? "" : n.gid
				}, [(U(), Qi(kr(p.value === n.gid ? I(ws) : I(Ss)), { size: 15 }))], 8, mu)]),
				p.value === n.gid ? (U(), W("div", hu, [G("span", gu, k(n.directory || "默认下载目录"), 1), G("div", _u, [
					G("label", vu, [T[35] ||= q("下载速度", -1), G("select", {
						"aria-label": "下载速度限制",
						onChange: (e) => C(n, e.target.value)
					}, [...T[34] ||= [
						G("option", { value: "0" }, "不限速", -1),
						G("option", { value: "1048576" }, "1 MB/s", -1),
						G("option", { value: "5242880" }, "5 MB/s", -1),
						G("option", { value: "10485760" }, "10 MB/s", -1)
					]], 40, yu)]),
					["complete", "removed"].includes(n.status) ? J("", !0) : (U(), W("button", {
						key: 0,
						class: "nx-button nx-quiet",
						disabled: !!t.session.busy,
						onClick: (e) => S(n, "first")
					}, [K(I(bs), { size: 13 }), T[36] ||= q("优先下载", -1)], 8, bu)),
					n.status === "complete" ? (U(), W("button", {
						key: 1,
						class: "nx-button nx-quiet",
						disabled: !!t.session.busy,
						onClick: (e) => w(n)
					}, [K(I(qs), { size: 13 }), T[37] ||= q("校验文件", -1)], 8, xu)) : J("", !0),
					["complete", "removed"].includes(n.status) ? J("", !0) : (U(), W("button", {
						key: 2,
						class: "nx-button nx-quiet nx-danger-text",
						disabled: !!t.session.busy,
						onClick: (e) => S(n, "cancel")
					}, [K(I(Zs), { size: 13 }), T[38] ||= q("取消下载 ", -1)], 8, Su))
				])])) : J("", !0)
			], 8, nu))), 128)), h.value.length ? J("", !0) : (U(), W("div", Cu, [
				K(I(Os), {
					size: 32,
					"stroke-width": 1.3
				}),
				G("strong", null, k(r.value === "complete" ? "还没有完成的下载" : "准备好下载了吗？"), 1),
				G("p", null, k(r.value === "complete" ? "完成的文件会显示在这里。" : "把链接放到上面的框里，就会开始下载。"), 1)
			]))])
		]));
	}
}, Tu = { class: "nx-view-stack" }, Eu = { class: "nx-panel nx-diagnose-start" }, Du = { class: "nx-diagnose-symbol" }, Ou = { class: "nx-input-with-icon" }, ku = ["disabled"], Au = { class: "nx-diagnose-options" }, ju = {
	key: 0,
	class: "nx-panel nx-diagnose-pending",
	"aria-live": "polite"
}, Mu = {
	key: 1,
	class: "nx-panel nx-report"
}, Nu = { class: "nx-report-heading" }, Pu = { class: "nx-check-list" }, Fu = { key: 0 }, Iu = {
	key: 0,
	class: "nx-report-advice"
}, Lu = ["aria-expanded"], Ru = {
	key: 1,
	class: "nx-check-evidence"
}, zu = {
	key: 2,
	class: "nx-history"
}, Bu = { class: "nx-section-heading" }, Vu = { class: "nx-subtle" }, Hu = ["onClick"], Uu = {
	key: 3,
	class: "nx-empty nx-diagnose-empty"
}, Wu = {
	__name: "DiagnoseView",
	props: {
		session: Object,
		report: Object
	},
	setup(e) {
		let t = e, n = /* @__PURE__ */ F("github.com"), r = /* @__PURE__ */ F(null), i = /* @__PURE__ */ F(!1), a = /* @__PURE__ */ F("basic");
		In(() => t.report, (e) => {
			e && (r.value = e, n.value = e.target);
		}, { immediate: !0 });
		let o = X(() => r.value || t.session.state?.reports?.at(-1));
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
		return (t, l) => (U(), W("div", Tu, [
			G("section", Eu, [
				G("div", Du, [K(I(hs), {
					size: 25,
					"stroke-width": 1.5
				})]),
				l[8] ||= G("h2", null, "看看哪里没连上", -1),
				l[9] ||= G("p", null, "输入一个网站，检查地址解析、连接和响应。", -1),
				G("form", {
					class: "nx-inline-form",
					"data-diagnose-form": "",
					onSubmit: Q(c, ["prevent"])
				}, [G("label", Ou, [K(I(Ps), { size: 16 }), R(G("input", {
					"onUpdate:modelValue": l[0] ||= (e) => n.value = e,
					name: "target",
					class: "nx-input",
					placeholder: "例如 github.com",
					required: "",
					"aria-label": "检测网站"
				}, null, 512), [[Z, n.value]])]), G("button", {
					class: "nx-button nx-primary",
					disabled: !!e.session.busy
				}, [K(I(Gs), { size: 15 }), q(k(e.session.busy === "diagnose" ? "检查中…" : "开始检测"), 1)], 8, ku)], 32),
				G("div", Au, [
					G("label", null, [R(G("input", {
						"onUpdate:modelValue": l[1] ||= (e) => a.value = e,
						type: "radio",
						value: "basic"
					}, null, 512), [[Go, a.value]]), l[5] ||= q("快速检查", -1)]),
					G("label", null, [R(G("input", {
						"onUpdate:modelValue": l[2] ||= (e) => a.value = e,
						type: "radio",
						value: "ping"
					}, null, 512), [[Go, a.value]]), l[6] ||= q("加测延迟", -1)]),
					G("label", null, [R(G("input", {
						"onUpdate:modelValue": l[3] ||= (e) => a.value = e,
						type: "radio",
						value: "traceroute"
					}, null, 512), [[Go, a.value]]), l[7] ||= q("查看访问路径", -1)])
				])
			]),
			e.session.busy === "diagnose" ? (U(), W("section", ju, [
				l[10] ||= G("div", { class: "nx-skeleton nx-skeleton-title" }, null, -1),
				l[11] ||= G("p", null, "正在检查网站地址、连接和安全响应…", -1),
				(U(), W(V, null, z(3, (e) => G("div", {
					key: e,
					class: "nx-skeleton nx-skeleton-row"
				})), 64))
			])) : o.value ? (U(), W("section", Mu, [
				G("div", Nu, [G("span", { class: O(["nx-result-icon", { "is-failure": o.value.failures > 0 }]) }, [o.value.failures ? (U(), Qi(I(Zs), {
					key: 1,
					size: 22
				})) : (U(), Qi(I(xs), {
					key: 0,
					size: 22
				}))], 2), G("div", null, [G("h2", null, k(o.value.failures > 0 ? "发现未通过的检查" : "检查通过"), 1), G("p", null, [
					q(k(o.value.target), 1),
					l[12] ||= G("span", { class: "nx-meta-divider" }, "·", -1),
					q(k(I(tc)(o.value.time)), 1)
				])])]),
				G("div", Pu, [(U(!0), W(V, null, z(o.value.checks || [], (e, t) => (U(), W("div", {
					key: t,
					class: "nx-check-row"
				}, [
					G("span", { class: O(["nx-check-status", { "is-failure": !e.ok }]) }, [e.ok ? (U(), Qi(I(xs), {
						key: 0,
						size: 14
					})) : (U(), Qi(I(Zs), {
						key: 1,
						size: 14
					}))], 2),
					G("strong", null, k(s(e.stage)), 1),
					G("span", null, k(e.ok ? "通过" : "未通过"), 1),
					e.ms == null ? J("", !0) : (U(), W("time", Fu, k(e.ms) + " ms", 1))
				]))), 128))]),
				o.value.recommendation ? (U(), W("p", Iu, k(o.value.recommendation), 1)) : J("", !0),
				G("button", {
					class: "nx-button nx-quiet nx-report-detail-button",
					"aria-expanded": i.value,
					onClick: l[4] ||= (e) => i.value = !i.value
				}, [q(k(i.value ? "收起" : "查看") + "检查详情", 1), K(I(Ss), { size: 13 })], 8, Lu),
				i.value ? (U(), W("div", Ru, [(U(!0), W(V, null, z(o.value.checks || [], (e, t) => (U(), W("div", { key: t }, [G("strong", null, k(s(e.stage)), 1), G("p", null, k(e.evidence || e.address || e.addresses?.join("、") || (e.status ? `网站响应：${e.status}` : "未提供额外信息")), 1)]))), 128))])) : J("", !0)
			])) : J("", !0),
			e.session.state?.reports?.length ? (U(), W("section", zu, [G("div", Bu, [l[13] ||= G("h2", null, "最近检查", -1), G("span", Vu, k(e.session.state.reports.length) + " 条记录", 1)]), (U(!0), W(V, null, z([...e.session.state.reports].reverse().slice(0, 12), (e) => (U(), W("button", {
				key: e.id,
				class: "nx-history-row",
				onClick: (t) => r.value = e
			}, [
				G("span", { class: O(["nx-history-result", { "is-failure": e.failures > 0 }]) }, [(U(), Qi(kr(e.failures ? I(Zs) : I(xs)), { size: 14 }))], 2),
				G("strong", null, k(e.target), 1),
				G("span", null, k(e.failures ? "有未通过的检查" : "检查通过"), 1),
				G("time", null, k(I(tc)(e.time)), 1),
				K(I(Cs), { size: 15 })
			], 8, Hu))), 128))])) : o.value ? J("", !0) : (U(), W("div", Uu, [K(I(Es), { size: 25 }), l[14] ||= G("span", null, "检查记录会保存在这里，方便下次对照。", -1)]))
		]));
	}
}, Gu = { class: "nx-view-stack" }, Ku = { class: "nx-section-heading" }, qu = ["aria-expanded"], Ju = { class: "nx-panel nx-interface-list" }, Yu = { class: "nx-control-icon" }, Xu = { key: 0 }, Zu = {
	key: 0,
	class: "nx-empty nx-empty--small"
}, Qu = { class: "nx-form-grid" }, $u = ["value"], ed = ["disabled"], td = { class: "nx-panel nx-form" }, nd = { class: "nx-panel-heading" }, rd = ["disabled"], id = {
	key: 0,
	class: "nx-query-result"
}, ad = { class: "nx-subtle" }, od = { key: 0 }, sd = { class: "nx-settings-fold" }, cd = ["aria-expanded"], ld = {
	key: 0,
	class: "nx-panel nx-form"
}, ud = ["onUpdate:modelValue"], dd = ["onUpdate:modelValue"], fd = ["onClick"], pd = { class: "nx-actions" }, md = ["disabled"], hd = ["disabled"], gd = { key: 0 }, _d = {
	__name: "NetworkSettings",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(!1), r = /* @__PURE__ */ F(""), i = /* @__PURE__ */ F("1.1.1.1,8.8.8.8"), a = /* @__PURE__ */ F("github.com"), o = /* @__PURE__ */ F("system"), s = /* @__PURE__ */ F(null), c = /* @__PURE__ */ F(!1), l = /* @__PURE__ */ F(null), u = /* @__PURE__ */ F(""), d = /* @__PURE__ */ F(null);
		async function f() {
			s.value = await t.session.run("dns.query", {
				domain: a.value.trim(),
				provider: o.value,
				type: "A"
			});
		}
		async function p() {
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
		function m() {
			l.value = (t.session.state.rules || []).map((e) => ({ ...e })), c.value = !c.value;
		}
		async function h() {
			await t.session.run("rules.save", {
				revision: t.session.state.revision,
				rules: l.value
			}, "规则已保存");
		}
		async function g() {
			d.value = await t.session.run("rules.test", { domain: u.value });
		}
		return (t, _) => (U(), W("div", Gu, [
			G("div", Ku, [_[8] ||= G("div", null, [G("h2", null, "本机网络"), G("p", null, "查看当前地址和正在使用的 DNS。")], -1), G("button", {
				class: "nx-button nx-secondary",
				"aria-expanded": n.value,
				onClick: _[0] ||= (e) => n.value = !n.value
			}, [K(I(Ks), { size: 15 }), _[7] ||= q("调整 DNS ", -1)], 8, qu)]),
			G("section", Ju, [(U(!0), W(V, null, z(e.session.interfaces, (e) => (U(), W("article", {
				key: e.index,
				class: "nx-interface"
			}, [G("span", Yu, [K(I(Ls), { size: 20 })]), G("div", null, [G("strong", null, k(e.name), 1), G("dl", null, [
				G("div", null, [_[9] ||= G("dt", null, "本机地址", -1), G("dd", null, k(e.ipv4?.join("、") || "没有 IPv4 地址"), 1)]),
				G("div", null, [_[10] ||= G("dt", null, "DNS", -1), G("dd", null, k(e.dns?.join("、") || "由系统提供"), 1)]),
				e.gateway?.length ? (U(), W("div", Xu, [_[11] ||= G("dt", null, "网关", -1), G("dd", null, k(e.gateway.join("、")), 1)])) : J("", !0)
			])])]))), 128)), e.session.interfaces.length ? J("", !0) : (U(), W("div", Zu, [K(I(Ls), { size: 25 }), _[12] ||= G("span", null, "暂时没有读取到网络接口。", -1)]))]),
			n.value ? (U(), W("form", {
				key: 0,
				class: "nx-panel nx-form",
				onSubmit: Q(p, ["prevent"])
			}, [
				_[16] ||= G("h2", null, "调整 DNS", -1),
				G("div", Qu, [G("label", null, [_[14] ||= G("span", null, "网络接口", -1), R(G("select", {
					"onUpdate:modelValue": _[1] ||= (e) => r.value = e,
					class: "nx-input",
					required: "",
					"aria-label": "网络接口"
				}, [_[13] ||= G("option", {
					disabled: "",
					value: ""
				}, "选择正在使用的网络", -1), (U(!0), W(V, null, z(e.session.interfaces, (e) => (U(), W("option", {
					key: e.index,
					value: e.index
				}, k(e.name), 9, $u))), 128))], 512), [[Ko, r.value]])]), G("label", null, [_[15] ||= G("span", null, "DNS 地址", -1), R(G("input", {
					"onUpdate:modelValue": _[2] ||= (e) => i.value = e,
					class: "nx-input",
					required: "",
					placeholder: "多个地址用逗号隔开"
				}, null, 512), [[Z, i.value]])])]),
				_[17] ||= G("p", { class: "nx-help" }, "修改前会保存原设置，之后可在“防护”中恢复。", -1),
				G("button", {
					class: "nx-button nx-secondary",
					disabled: !!e.session.busy
				}, " 确认并申请修改 ", 8, ed)
			], 32)) : J("", !0),
			G("section", td, [
				G("div", nd, [G("h2", null, [K(I(Ps), { size: 17 }), _[18] ||= q("查询网站地址", -1)])]),
				G("form", {
					class: "nx-inline-form",
					onSubmit: Q(f, ["prevent"])
				}, [
					R(G("input", {
						"onUpdate:modelValue": _[3] ||= (e) => a.value = e,
						class: "nx-input",
						placeholder: "输入域名",
						"aria-label": "查询域名",
						required: ""
					}, null, 512), [[Z, a.value]]),
					R(G("select", {
						"onUpdate:modelValue": _[4] ||= (e) => o.value = e,
						class: "nx-input nx-fit-select",
						"aria-label": "查询方式"
					}, [..._[19] ||= [
						G("option", { value: "system" }, "系统 DNS", -1),
						G("option", { value: "cloudflare" }, "Cloudflare", -1),
						G("option", { value: "google" }, "Google", -1)
					]], 512), [[Ko, o.value]]),
					G("button", {
						class: "nx-button nx-secondary",
						disabled: !!e.session.busy
					}, [K(I(Gs), { size: 14 }), _[20] ||= q("查询 ", -1)], 8, rd)
				], 32),
				s.value ? (U(), W("div", id, [
					G("span", ad, k(s.value.domain) + " · " + k(s.value.ms || 0) + " ms", 1),
					(U(!0), W(V, null, z(s.value.addresses || s.value.answers || [], (e, t) => (U(), W("div", {
						key: t,
						class: "nx-query-address"
					}, k(typeof e == "string" ? e : e.data), 1))), 128)),
					(s.value.addresses || s.value.answers || []).length ? J("", !0) : (U(), W("span", od, "没有查到地址"))
				])) : J("", !0)
			]),
			G("section", sd, [G("button", {
				class: "nx-button nx-quiet",
				"aria-expanded": c.value,
				onClick: m
			}, [_[21] ||= q(" 网站规则匹配预览", -1), K(I(Ss), { size: 13 })], 8, cd), c.value ? (U(), W("div", ld, [
				_[24] ||= G("p", { class: "nx-help" }, " 用于检查匹配结果；实际代理分流以订阅中的规则为准。 ", -1),
				(U(!0), W(V, null, z(l.value, (e, t) => (U(), W("div", {
					key: t,
					class: "nx-rule-row"
				}, [
					R(G("input", {
						"onUpdate:modelValue": (t) => e.domain = t,
						class: "nx-input",
						placeholder: "例如 github.com",
						"aria-label": "规则域名"
					}, null, 8, ud), [[Z, e.domain]]),
					R(G("select", {
						"onUpdate:modelValue": (t) => e.outbound = t,
						class: "nx-input",
						"aria-label": "规则出口"
					}, [..._[22] ||= [
						G("option", { value: "DIRECT" }, "直接连接", -1),
						G("option", { value: "PROXY" }, "通过代理", -1),
						G("option", { value: "REJECT" }, "阻止连接", -1)
					]], 8, dd), [[Ko, e.outbound]]),
					G("button", {
						class: "nx-button nx-quiet nx-icon-button",
						"aria-label": "删除规则",
						onClick: (e) => l.value.splice(t, 1)
					}, [K(I(Zs), { size: 14 })], 8, fd)
				]))), 128)),
				G("div", pd, [G("button", {
					class: "nx-button nx-quiet",
					onClick: _[5] ||= (e) => l.value.push({
						domain: "",
						outbound: "DIRECT"
					})
				}, [K(I(Vs), { size: 14 }), _[23] ||= q("添加规则", -1)]), G("button", {
					class: "nx-button nx-secondary",
					disabled: !!e.session.busy,
					onClick: h
				}, " 保存规则 ", 8, md)]),
				G("form", {
					class: "nx-inline-form",
					onSubmit: Q(g, ["prevent"])
				}, [R(G("input", {
					"onUpdate:modelValue": _[6] ||= (e) => u.value = e,
					class: "nx-input",
					required: "",
					placeholder: "输入域名，看看会匹配到哪里",
					"aria-label": "测试规则域名"
				}, null, 512), [[Z, u.value]]), G("button", {
					class: "nx-button nx-secondary",
					disabled: !!e.session.busy
				}, " 测试匹配 ", 8, hd)], 32),
				d.value ? (U(), W("p", gd, k(d.value.matched ? `匹配到 ${d.value.matched.domain}` : "未匹配到专属规则") + " · " + k({
					DIRECT: "直接连接",
					PROXY: "通过代理",
					REJECT: "阻止连接"
				}[d.value.outbound]), 1)) : J("", !0)
			])) : J("", !0)])
		]));
	}
}, vd = { class: "nx-view-stack" }, yd = { class: "nx-section-heading" }, bd = { class: "nx-subtle" }, xd = { class: "nx-input-with-icon" }, Sd = ["disabled"], Cd = { class: "nx-panel nx-table-panel" }, wd = {
	key: 0,
	class: "nx-table-loading"
}, Td = {
	key: 1,
	class: "nx-table-scroll"
}, Ed = { class: "nx-table" }, Dd = ["title"], Od = { key: 0 }, kd = { class: "nx-data-cell" }, Ad = { class: "nx-protocol" }, jd = {
	key: 0,
	class: "nx-empty"
}, Md = {
	__name: "ConnectionsView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(""), r = /* @__PURE__ */ F([]), i = /* @__PURE__ */ F(0), a = /* @__PURE__ */ F(150), o = /* @__PURE__ */ F(!0);
		async function s() {
			o.value = !0;
			let e = await t.session.read("connections", { filter: n.value });
			e && (r.value = e.connections || [], i.value = e.total || r.value.length, a.value = 150), o.value = !1;
		}
		let c = X(() => r.value.slice(0, a.value));
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
		return vr(s), (e, t) => (U(), W("div", vd, [
			G("div", yd, [t[2] ||= G("div", null, [G("h2", null, "应用正在连接什么"), G("p", null, "按应用、地址或端口查找当前连接。")], -1), G("span", bd, k(i.value) + " 个连接", 1)]),
			G("form", {
				class: "nx-inline-form nx-searchbar",
				onSubmit: Q(s, ["prevent"])
			}, [G("label", xd, [K(I(Gs), { size: 16 }), R(G("input", {
				"onUpdate:modelValue": t[0] ||= (e) => n.value = e,
				class: "nx-input",
				placeholder: "搜索应用、IP 或端口",
				"aria-label": "搜索连接"
			}, null, 512), [[Z, n.value]])]), G("button", {
				class: "nx-button nx-secondary",
				disabled: o.value
			}, [K(I(Ws), { size: 14 }), t[3] ||= q("刷新 ", -1)], 8, Sd)], 32),
			G("section", Cd, [o.value ? (U(), W("div", wd, [(U(), W(V, null, z(5, (e) => G("div", {
				key: e,
				class: "nx-skeleton nx-skeleton-row"
			})), 64))])) : (U(), W("div", Td, [G("table", Ed, [t[4] ||= G("thead", null, [G("tr", null, [
				G("th", null, "应用"),
				G("th", null, "本地端口"),
				G("th", null, "远端地址"),
				G("th", null, "协议"),
				G("th", null, "状态")
			])], -1), G("tbody", null, [(U(!0), W(V, null, z(c.value, (e, t) => (U(), W("tr", { key: t }, [
				G("td", { title: e.path || "" }, [G("strong", null, k(e.process || "未知应用"), 1), e.pid ? (U(), W("small", Od, "PID " + k(e.pid), 1)) : J("", !0)], 8, Dd),
				G("td", null, k(e.local_port), 1),
				G("td", kd, k(e.remote_address ? `${e.remote_address}:${e.remote_port}` : "—"), 1),
				G("td", null, [G("span", Ad, k(e.protocol), 1)]),
				G("td", null, [G("span", { class: O(["nx-connection-state", { "is-live": e.state === "Established" }]) }, k(l(e.state)), 3)])
			]))), 128))])]), r.value.length ? J("", !0) : (U(), W("div", jd, [
				K(I(vs), { size: 28 }),
				t[5] ||= G("strong", null, "没有匹配的连接", -1),
				t[6] ||= G("p", null, "试着输入其他应用名称、地址或端口。", -1)
			]))])), r.value.length > a.value ? (U(), W("button", {
				key: 2,
				class: "nx-button nx-quiet nx-load-more",
				onClick: t[1] ||= (e) => a.value += 150
			}, " 再显示 150 个连接 ")) : J("", !0)]),
			t[7] ||= G("p", { class: "nx-help" }, "这里显示连接和端口，不代表每个应用的流量大小。", -1)
		]));
	}
}, Nd = { class: "nx-view-stack" }, Pd = { class: "nx-section-heading" }, Fd = {
	key: 0,
	class: "nx-panel nx-form"
}, Id = { class: "nx-inline-form" }, Ld = ["value"], Rd = { class: "nx-application-actions" }, zd = ["disabled"], Bd = { class: "nx-inline-form" }, Vd = ["disabled"], Hd = { class: "nx-panel nx-transaction-list" }, Ud = { class: "nx-panel-heading" }, Wd = { class: "nx-subtle" }, Gd = { class: "nx-transaction-icon" }, Kd = { key: 0 }, qd = ["disabled", "onClick"], Jd = {
	key: 0,
	class: "nx-empty"
}, Yd = {
	__name: "SecurityView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(!1), r = /* @__PURE__ */ F([]), i = /* @__PURE__ */ F(""), a = /* @__PURE__ */ F(!1), o = /* @__PURE__ */ F("8000000"), s = X(() => [...t.session.state?.transactions || []].reverse());
		async function c() {
			n.value = !0;
			let e = await t.session.read("connections", {}), i = /* @__PURE__ */ new Set();
			r.value = (e?.connections || []).filter((e) => e.path && !i.has(e.path) && i.add(e.path)).sort((e, t) => (e.process || "").localeCompare(t.process || ""));
		}
		async function l(e) {
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
		function u(e) {
			return {
				proxy: "系统代理",
				dns: "DNS 设置",
				firewall: "应用联网限制",
				qos: "应用上传限速"
			}[e.request?.kind] || "网络设置";
		}
		function d(e) {
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
		return (t, f) => (U(), W("div", Nd, [
			G("div", Pd, [f[7] ||= G("div", null, [G("h2", null, "应用联网与恢复"), G("p", null, "只修改你选择的应用，随时检查并恢复原设置。")], -1), G("button", {
				class: "nx-button nx-secondary",
				onClick: c
			}, [K(I(Ls), { size: 15 }), f[6] ||= q("选择应用 ", -1)])]),
			n.value ? (U(), W("section", Fd, [
				f[15] ||= G("h2", null, "管理一个应用", -1),
				G("div", Id, [a.value ? R((U(), W("input", {
					key: 0,
					"onUpdate:modelValue": f[0] ||= (e) => i.value = e,
					class: "nx-input",
					placeholder: "应用 .exe 的完整路径",
					"aria-label": "应用路径"
				}, null, 512)), [[Z, i.value]]) : R((U(), W("select", {
					key: 1,
					"onUpdate:modelValue": f[1] ||= (e) => i.value = e,
					class: "nx-input",
					"aria-label": "选择应用"
				}, [f[8] ||= G("option", {
					disabled: "",
					value: ""
				}, "从当前连接的应用中选择", -1), (U(!0), W(V, null, z(r.value, (e) => (U(), W("option", {
					key: e.path,
					value: e.path
				}, k(e.process) + " · " + k(e.path.split("\\").at(-1)), 9, Ld))), 128))], 512)), [[Ko, i.value]]), G("button", {
					class: "nx-button nx-quiet",
					onClick: f[2] ||= (e) => {
						a.value = !a.value, i.value = "";
					}
				}, k(a.value ? "从列表选择" : "手动输入路径"), 1)]),
				G("div", Rd, [G("div", null, [
					f[10] ||= G("h3", null, "阻止这个应用联网", -1),
					f[11] ||= G("p", null, "创建仅作用于该应用的出站防火墙规则。", -1),
					G("button", {
						class: "nx-button nx-secondary nx-danger-text",
						disabled: !i.value || !!e.session.busy,
						onClick: f[3] ||= (e) => l("firewall")
					}, [K(I(Js), { size: 14 }), f[9] ||= q("申请阻止联网 ", -1)], 8, zd)
				]), G("div", null, [
					f[13] ||= G("h3", null, "限制这个应用的上传", -1),
					f[14] ||= G("p", null, "降低后台上传对其他任务的影响。", -1),
					G("div", Bd, [R(G("select", {
						"onUpdate:modelValue": f[4] ||= (e) => o.value = e,
						class: "nx-input",
						"aria-label": "应用上传速度上限"
					}, [...f[12] ||= [
						G("option", { value: "8000000" }, "1 MB/s", -1),
						G("option", { value: "40000000" }, "5 MB/s", -1),
						G("option", { value: "80000000" }, "10 MB/s", -1)
					]], 512), [[Ko, o.value]]), G("button", {
						class: "nx-button nx-secondary",
						disabled: !i.value || !!e.session.busy,
						onClick: f[5] ||= (e) => l("qos")
					}, " 申请限速 ", 8, Vd)])
				])]),
				f[16] ||= G("p", { class: "nx-help" }, " 这两项操作可能需要 Windows 管理员权限，执行前会显示影响范围。 ", -1)
			])) : J("", !0),
			G("section", Hd, [
				G("div", Ud, [G("h2", null, [K(I(Xs), { size: 17 }), f[17] ||= q("网络设置记录", -1)]), G("span", Wd, k(s.value.length) + " 条", 1)]),
				(U(!0), W(V, null, z(s.value, (t) => (U(), W("article", {
					key: t.id,
					class: "nx-transaction"
				}, [
					G("span", Gd, [K(I(qs), { size: 18 })]),
					G("div", null, [
						G("strong", null, k(u(t)), 1),
						t.request?.program ? (U(), W("p", Kd, k(t.request.program.split("\\").at(-1)), 1)) : J("", !0),
						G("small", null, k(I(tc)(t.time)), 1)
					]),
					G("span", { class: O(["nx-status-text", { "is-warning": ["external_change", "recovery_required"].includes(t.status) }]) }, k(d(t.status)), 3),
					[
						"applied",
						"prepared",
						"recovery_required"
					].includes(t.status) ? (U(), W("button", {
						key: 0,
						class: "nx-button nx-secondary",
						disabled: !!e.session.busy,
						onClick: (n) => e.session.run("system.restore", { id: t.id }, "已检查并恢复原设置")
					}, [K(I(Xs), { size: 13 }), f[18] ||= q("恢复 ", -1)], 8, qd)) : J("", !0)
				]))), 128)),
				s.value.length ? J("", !0) : (U(), W("div", Jd, [
					K(I(qs), {
						size: 31,
						"stroke-width": 1.4
					}),
					f[19] ||= G("strong", null, "还没有修改网络设置", -1),
					f[20] ||= G("p", null, "通过这里执行的修改，会留下可恢复的记录。", -1)
				]))
			]),
			f[21] ||= G("p", { class: "nx-help" }, " 如果设置已被其他软件或用户修改，会保留当前状态，避免直接覆盖。 ", -1)
		]));
	}
}, Xd = { class: "nx-view-stack" }, Zd = { class: "nx-panel" }, Qd = { class: "nx-panel-heading" }, $d = ["disabled"], ef = [
	"aria-label",
	"aria-checked",
	"disabled",
	"onClick"
], tf = ["disabled", "onClick"], nf = ["disabled", "onClick"], rf = {
	key: 1,
	class: "nx-empty-inline"
}, af = { class: "nx-panel" }, of = { class: "nx-panel-heading" }, sf = ["disabled"], cf = {
	key: 1,
	class: "nx-table-scroll"
}, lf = { class: "nx-table" }, uf = {
	key: 0,
	class: "nx-empty-inline"
}, df = { class: "nx-panel nx-settings-rows" }, ff = ["disabled"], pf = {
	key: 0,
	class: "nx-recent"
}, mf = { class: "nx-section-heading" }, hf = { class: "nx-subtle" }, gf = {
	__name: "AdvancedView",
	props: { session: Object },
	setup(e) {
		let t = e, n = /* @__PURE__ */ F(!1), r = /* @__PURE__ */ F("github.com"), i = /* @__PURE__ */ F("30"), a = /* @__PURE__ */ F(null), o = /* @__PURE__ */ F(String(t.session.state?.settings?.sample_seconds || 5));
		async function s(e) {
			return t.session.run("automation.save", {
				revision: t.session.state.revision,
				automations: e
			}, "定时检查已更新");
		}
		async function c() {
			let e = r.value.trim();
			try {
				e.includes("://") && (e = new URL(e).hostname);
			} catch {
				t.session.error = "请输入有效的网址";
				return;
			}
			await s([...t.session.state.automations || [], {
				target: e,
				action: "diagnose",
				enabled: !0,
				interval_minutes: Number(i.value)
			}]) && (n.value = !1);
		}
		async function l(e) {
			await s(t.session.state.automations.map((t, n) => ({
				...t,
				...n === e ? { enabled: !t.enabled } : {}
			})));
		}
		async function u(e) {
			await s(t.session.state.automations.filter((t, n) => n !== e));
		}
		async function d(e) {
			let n = await t.session.run("automation.run", {
				index: e,
				dry_run: !0
			});
			n && (t.session.notice = `这条计划会检查 ${n.would_execute?.target || ""}，不会修改网络设置。`);
		}
		async function f() {
			let e = await t.session.run("export");
			if (!e) return;
			let n = URL.createObjectURL(new Blob([JSON.stringify(e, null, 2)], { type: "application/json" })), r = document.createElement("a");
			r.href = n, r.download = "network-reports.json", r.click(), setTimeout(() => URL.revokeObjectURL(n), 1e3);
		}
		async function p() {
			a.value = await t.session.read("lan");
		}
		return (t, s) => (U(), W("div", Xd, [
			G("section", Zd, [
				G("div", Qd, [G("h2", null, [K(I(Es), { size: 17 }), s[5] ||= q("定时检查", -1)]), G("button", {
					class: "nx-button nx-quiet",
					onClick: s[0] ||= (e) => n.value = !n.value
				}, [K(I(Vs), { size: 14 }), s[6] ||= q("添加 ", -1)])]),
				s[10] ||= G("p", { class: "nx-help" }, "定期检查常用网站，结果会保存在“检测”中。", -1),
				n.value ? (U(), W("form", {
					key: 0,
					class: "nx-inline-form nx-schedule-form",
					onSubmit: Q(c, ["prevent"])
				}, [
					R(G("input", {
						"onUpdate:modelValue": s[1] ||= (e) => r.value = e,
						class: "nx-input",
						required: "",
						placeholder: "检查哪个网站",
						"aria-label": "定时检查的网站"
					}, null, 512), [[Z, r.value]]),
					R(G("select", {
						"onUpdate:modelValue": s[2] ||= (e) => i.value = e,
						class: "nx-input nx-fit-select",
						"aria-label": "检查间隔"
					}, [...s[7] ||= [
						G("option", { value: "15" }, "每 15 分钟", -1),
						G("option", { value: "30" }, "每 30 分钟", -1),
						G("option", { value: "60" }, "每小时", -1),
						G("option", { value: "360" }, "每 6 小时", -1)
					]], 512), [[Ko, i.value]]),
					G("button", {
						class: "nx-button nx-secondary",
						disabled: !!e.session.busy
					}, " 添加计划 ", 8, $d)
				], 32)) : J("", !0),
				(U(!0), W(V, null, z(e.session.state?.automations || [], (t, n) => (U(), W("article", {
					key: n,
					class: "nx-schedule-row"
				}, [
					G("button", {
						class: "nx-switch nx-switch--small",
						role: "switch",
						"aria-label": `${t.target} 定时检查`,
						"aria-checked": t.enabled,
						disabled: !!e.session.busy,
						onClick: (e) => l(n)
					}, [...s[8] ||= [G("span", null, null, -1)]], 8, ef),
					G("div", null, [G("strong", null, k(t.target), 1), G("small", null, "每 " + k(t.interval_minutes) + " 分钟检查一次", 1)]),
					G("button", {
						class: "nx-button nx-quiet",
						disabled: !!e.session.busy,
						onClick: (e) => d(n)
					}, [K(I(Bs), { size: 13 }), s[9] ||= q("试运行", -1)], 8, tf),
					G("button", {
						class: "nx-button nx-quiet nx-icon-button",
						disabled: !!e.session.busy,
						"aria-label": "删除定时检查",
						onClick: (e) => u(n)
					}, [K(I(Zs), { size: 14 })], 8, nf)
				]))), 128)),
				!e.session.state?.automations?.length && !n.value ? (U(), W("p", rf, " 还没有计划，需要时再添加。 ")) : J("", !0)
			]),
			G("section", af, [
				G("div", of, [G("h2", null, [K(I(Ls), { size: 17 }), s[11] ||= q("本地设备", -1)]), G("button", {
					class: "nx-button nx-quiet",
					onClick: p
				}, " 查看设备 ")]),
				s[13] ||= G("p", { class: "nx-help" }, "查看系统记录过的局域网邻居。", -1),
				a.value ? J("", !0) : (U(), W("button", {
					key: 0,
					class: "nx-button nx-secondary",
					disabled: !!e.session.busy,
					onClick: p
				}, " 读取设备列表 ", 8, sf)),
				a.value?.devices ? (U(), W("div", cf, [G("table", lf, [s[12] ||= G("thead", null, [G("tr", null, [
					G("th", null, "设备地址"),
					G("th", null, "硬件地址"),
					G("th", null, "状态")
				])], -1), G("tbody", null, [(U(!0), W(V, null, z(a.value.devices, (e, t) => (U(), W("tr", { key: t }, [
					G("td", null, k(e.IPAddress), 1),
					G("td", null, k(e.LinkLayerAddress || "—"), 1),
					G("td", null, k(e.state), 1)
				]))), 128))])]), a.value.devices.length ? J("", !0) : (U(), W("p", uf, " 没有读取到设备记录。 "))])) : J("", !0)
			]),
			G("section", df, [G("div", null, [s[15] ||= G("span", null, [G("strong", null, "网速更新频率"), G("small", null, "降低更新频率可以减少后台采样。")], -1), R(G("select", {
				"onUpdate:modelValue": s[3] ||= (e) => o.value = e,
				class: "nx-input nx-fit-select",
				"aria-label": "网速采样间隔",
				onChange: s[4] ||= (t) => e.session.run("settings.update", {
					revision: e.session.state.revision,
					settings: { sample_seconds: Number(o.value) }
				}, "更新频率已保存")
			}, [...s[14] ||= [
				G("option", { value: "2" }, "每 2 秒", -1),
				G("option", { value: "5" }, "每 5 秒", -1),
				G("option", { value: "10" }, "每 10 秒", -1),
				G("option", { value: "30" }, "每 30 秒", -1)
			]], 544), [[Ko, o.value]])]), G("div", null, [s[17] ||= G("span", null, [G("strong", null, "导出检查记录"), G("small", null, "保存检查结果和近期事件，方便对照。")], -1), G("button", {
				class: "nx-button nx-secondary",
				disabled: !!e.session.busy,
				onClick: f
			}, [K(I(js), { size: 14 }), s[16] ||= q("导出 ", -1)], 8, ff)])]),
			e.session.state?.events?.length ? (U(), W("section", pf, [G("div", mf, [s[18] ||= G("h2", null, "活动记录", -1), G("span", hf, "最近 " + k(Math.min(e.session.state.events.length, 40)) + " 条", 1)]), (U(!0), W(V, null, z([...e.session.state.events].reverse().slice(0, 40), (e, t) => (U(), W("div", {
				key: t,
				class: "nx-event"
			}, [
				K(I(xs), { size: 14 }),
				G("span", null, k(e.message), 1),
				G("time", null, k(I(tc)(e.time)), 1)
			]))), 128))])) : J("", !0)
		]));
	}
}, _f = ["aria-busy"], vf = { class: "nx-sidebar" }, yf = {
	class: "nx-brand",
	title: "Network Exploration"
}, bf = { "aria-label": "网络工具" }, xf = [
	"data-page",
	"aria-current",
	"title",
	"onClick"
], Sf = { class: "nx-sidebar-foot" }, Cf = { class: "nx-workspace" }, wf = { class: "nx-header" }, Tf = { class: "nx-header-actions" }, Ef = {
	key: 0,
	class: "nx-working"
}, Df = {
	key: 1,
	class: "nx-live-label"
}, Of = ["disabled"], kf = {
	key: 0,
	class: "nx-notice nx-notice--error",
	role: "alert"
}, Af = ["role"], jf = { class: "nx-content ne-content" }, Mf = {
	key: "loading",
	class: "nx-loading",
	"aria-live": "polite"
}, Nf = "network-exploration:page", Pf = {
	__name: "NetworkApp",
	props: { context: {
		type: Object,
		required: !0
	} },
	setup(e) {
		let t = ac(e.context), n = /* @__PURE__ */ F(null), r = [
			{
				id: "home",
				title: "首页",
				hint: "实时数据与常用操作",
				icon: Fs,
				component: Oc
			},
			{
				id: "overview",
				title: "加速",
				hint: "本机加速开关与运行状态",
				icon: Qs,
				component: rl
			},
			{
				id: "proxy",
				title: "代理",
				hint: "订阅、节点与连接方式",
				icon: Ps,
				component: Hl
			},
			{
				id: "transfer",
				title: "下载",
				hint: "文件下载与任务",
				icon: Os,
				component: wu
			},
			{
				id: "diagnose",
				title: "检测",
				hint: "检查网站连接",
				icon: hs,
				component: Wu
			},
			{
				id: "network",
				title: "网络",
				hint: "接口与 DNS",
				icon: Ks,
				component: _d
			},
			{
				id: "traffic",
				title: "连接",
				hint: "应用与端口",
				icon: vs,
				component: Md
			},
			{
				id: "security",
				title: "防护",
				hint: "应用联网与恢复",
				icon: qs,
				component: Yd
			},
			{
				id: "advanced",
				title: "更多",
				hint: "定时检测与记录",
				icon: Ys,
				component: gf
			}
		], i = r.filter((e) => [
			"home",
			"overview",
			"proxy",
			"transfer"
		].includes(e.id));
		function a() {
			try {
				let e = sessionStorage.getItem(Nf);
				return sessionStorage.removeItem(Nf), r.some((t) => t.id === e) ? e : "home";
			} catch {
				return "home";
			}
		}
		let o = /* @__PURE__ */ F(a());
		function s(e) {
			let t = e.detail?.page;
			if (r.some((e) => e.id === t)) {
				l(t);
				try {
					sessionStorage.removeItem(Nf);
				} catch {}
			}
		}
		vr(() => window.addEventListener("sunday:network-plugin-page", s)), xr(() => window.removeEventListener("sunday:network-plugin-page", s));
		let c = X(() => r.find((e) => e.id === o.value));
		function l(e) {
			o.value = e, t.notice = "", t.error = "";
		}
		function u(e) {
			n.value = e, o.value = "diagnose";
		}
		return (e, r) => (U(), W("div", {
			class: "nx-app",
			"aria-busy": !!I(t).busy
		}, [G("aside", vf, [
			G("div", yf, [K(I(Rs), {
				size: 25,
				"stroke-width": 1.7
			}), r[4] ||= G("span", null, "Network", -1)]),
			G("nav", bf, [(U(!0), W(V, null, z(I(i), (e) => (U(), W("button", {
				key: e.id,
				class: O(["nx-nav-item", { "is-active": o.value === e.id }]),
				"data-page": e.id,
				"aria-current": o.value === e.id ? "page" : void 0,
				title: e.hint,
				onClick: (t) => l(e.id)
			}, [(U(), Qi(kr(e.icon), {
				size: 20,
				"stroke-width": 1.65
			})), G("span", null, k(e.title), 1)], 10, xf))), 128))]),
			G("div", Sf, [G("span", { class: O(["nx-live-dot", { "is-offline": !!I(t).connectionError || !I(t).state }]) }, null, 2), G("span", null, k(I(t).connectionError ? "离线" : I(t).state ? "监测中" : "连接中"), 1)])
		]), G("div", Cf, [
			G("header", wf, [G("div", null, [
				r[5] ||= G("span", { class: "nx-eyebrow" }, "NETWORK CONSOLE", -1),
				G("h1", null, k(c.value.title), 1),
				G("p", null, k(c.value.hint), 1)
			]), G("div", Tf, [I(t).busy ? (U(), W("span", Ef, "正在处理…")) : I(t).state && !I(t).connectionError ? (U(), W("span", Df, [...r[6] ||= [G("span", { class: "nx-live-dot" }, null, -1), q("实时更新", -1)]])) : J("", !0), G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				disabled: !!I(t).busy,
				"aria-label": "刷新网络状态",
				onClick: r[0] ||= (e) => I(t).refresh()
			}, [K(I(Ws), { size: 17 })], 8, Of)])]),
			I(t).connectionError ? (U(), W("div", kf, [r[7] ||= G("span", null, "暂时无法连接网络服务，请稍后重试。", -1), G("button", {
				class: "nx-button nx-quiet",
				onClick: r[1] ||= (e) => I(t).refresh()
			}, "重试")])) : J("", !0),
			I(t).error || I(t).notice ? (U(), W("div", {
				key: 1,
				class: O(["nx-notice", { "nx-notice--error": I(t).error }]),
				role: I(t).error ? "alert" : "status"
			}, [G("span", null, k(I(t).error || I(t).notice), 1), G("button", {
				class: "nx-button nx-quiet nx-icon-button",
				"aria-label": "关闭提示",
				onClick: r[2] ||= (e) => {
					I(t).error = "", I(t).notice = "";
				}
			}, [K(I(Zs), { size: 14 })])], 10, Af)) : J("", !0),
			G("main", jf, [K(qa, { name: "nx-page" }, {
				default: An(() => [I(t).state ? (U(), Qi(kr(c.value.component), {
					key: o.value,
					session: I(t),
					report: n.value,
					onNavigate: l,
					onDiagnostic: u
				}, null, 40, ["session", "report"])) : (U(), W("div", Mf, [
					r[8] ||= G("div", { class: "nx-skeleton nx-loading-banner" }, null, -1),
					r[9] ||= G("div", { class: "nx-loading-grid" }, [G("div", { class: "nx-skeleton nx-loading-chart" }), G("div", { class: "nx-skeleton nx-loading-chart" })], -1),
					r[10] ||= G("p", null, "正在读取网络状态…", -1),
					I(t).connectionError ? (U(), W("button", {
						key: 0,
						class: "nx-button nx-secondary",
						onClick: r[3] ||= (e) => I(t).refresh()
					}, " 重新连接 ")) : J("", !0)
				]))]),
				_: 1
			})])
		])], 8, _f));
	}
}, Ff = {
	class: "nx-app nx-quick-app",
	"aria-label": "网络快捷操作"
}, If = { class: "nx-pill-list" }, Lf = {
	class: "nx-pill-icon",
	title: "加速"
}, Rf = [
	"aria-pressed",
	"aria-label",
	"title",
	"disabled"
], zf = {
	class: "nx-pill-icon",
	title: "代理"
}, Bf = { class: "nx-node-wrap" }, Vf = ["value", "disabled"], Hf = {
	key: 0,
	value: ""
}, Uf = ["value"], Wf = [
	"aria-pressed",
	"aria-label",
	"title",
	"disabled"
], Gf = {
	class: "nx-quick-pill",
	"data-quick": "download"
}, Kf = {
	class: "nx-pill-icon",
	title: "下载"
}, qf = ["disabled"], Jf = {
	key: 0,
	class: "nx-quick-error",
	role: "alert"
}, Yf = {
	key: 1,
	class: "nx-quick-note",
	role: "status"
}, Xf = {
	__name: "QuickPanel",
	props: { context: Object },
	setup(e) {
		let t = Object.create(e.context);
		t.compact = !0;
		let n = ac(t), r = /* @__PURE__ */ F(""), i = X(() => !!n.state?.proxy?.config_saved), a = X(() => !!n.state?.proxy?.running), o = X(() => Object.entries(n.proxy?.proxies || {}).filter(([e, t]) => e !== "GLOBAL" && Array.isArray(t.all) && t.type === "Selector")), s = X(() => o.value[0] || null), c = X(() => s.value?.[1]?.all || []), l = X(() => s.value?.[1]?.now || ""), u = X(() => n.systemProxyReady ? n.accelerated ? "已开启" : "未开启" : "读取中");
		function d(e) {
			try {
				sessionStorage.setItem("network-exploration:page", e);
			} catch {}
			window.dispatchEvent(new CustomEvent("sunday:open-plugin-page", { detail: {
				plugin: "network-exploration",
				id: "network"
			} })), window.dispatchEvent(new CustomEvent("sunday:network-plugin-page", { detail: { page: e } }));
		}
		function f() {
			if (!i.value) {
				d("proxy");
				return;
			}
			n.toggleProxy();
		}
		async function p(e) {
			let t = e.target.value;
			!t || !s.value || t === l.value || await n.selectNode(s.value[0], t);
		}
		async function m() {
			let e = r.value.trim();
			await n.run("transfer.add", { url: e }, "已开始下载") && (r.value = "", await n.loadTasks());
		}
		return (e, t) => (U(), W("section", Ff, [G("div", If, [
			G("div", {
				class: O(["nx-quick-pill", { "is-on": I(n).accelerated }]),
				"data-quick": "acceleration"
			}, [
				G("span", Lf, [K(I(Qs), { size: 16 })]),
				G("span", { class: O(["nx-pill-value", { "is-live": I(n).accelerated }]) }, k(u.value), 3),
				G("button", {
					class: O(["nx-mini-action", { "is-on": I(n).accelerated }]),
					"aria-pressed": I(n).accelerated,
					"aria-label": I(n).accelerated ? "关闭加速" : "开启加速",
					title: I(n).accelerated ? "关闭加速" : "开启加速",
					disabled: !!I(n).busy || !I(n).state || !I(n).systemProxyReady,
					"data-quick-action": "acceleration",
					onClick: t[0] ||= (e) => I(n).toggleAcceleration()
				}, [K(I(Hs), { size: 14 })], 10, Rf)
			], 2),
			G("div", {
				class: O(["nx-quick-pill", { "is-on": a.value }]),
				"data-quick": "proxy"
			}, [
				G("span", zf, [K(I(Ps), { size: 16 })]),
				G("div", Bf, [G("select", {
					class: "nx-node-select",
					value: l.value,
					disabled: !!I(n).busy || !c.value.length,
					"aria-label": "更换节点",
					title: "更换节点",
					onChange: p
				}, [c.value.length ? J("", !0) : (U(), W("option", Hf, "无可用节点")), (U(!0), W(V, null, z(c.value, (e) => (U(), W("option", {
					key: e,
					value: e
				}, k(e === "DIRECT" ? "直接连接" : e), 9, Uf))), 128))], 40, Vf), K(I(Ts), {
					size: 12,
					class: "nx-chevron"
				})]),
				G("button", {
					class: O(["nx-mini-action", { "is-on": a.value }]),
					"aria-pressed": a.value,
					"aria-label": a.value ? "关闭代理" : "开启代理",
					title: a.value ? "关闭代理" : "开启代理",
					disabled: !!I(n).busy || !I(n).state,
					"data-quick-action": "proxy",
					onClick: f
				}, [K(I(Hs), { size: 14 })], 10, Wf)
			], 2),
			G("div", Gf, [G("span", Kf, [K(I(Os), { size: 16 })]), G("form", {
				class: "nx-download-form",
				onSubmit: Q(m, ["prevent"])
			}, [R(G("input", {
				"onUpdate:modelValue": t[1] ||= (e) => r.value = e,
				type: "url",
				"aria-label": "下载链接",
				placeholder: "URL",
				required: ""
			}, null, 512), [[Z, r.value]]), G("button", {
				class: O(["nx-mini-action", { "is-ready": r.value.trim() }]),
				disabled: !!I(n).busy || !r.value.trim(),
				"aria-label": "开始下载",
				title: "开始下载"
			}, [K(I(gs), { size: 14 })], 10, qf)], 32)])
		]), I(n).error || I(n).connectionError ? (U(), W("p", Jf, k(I(n).error || "暂时无法连接网络服务"), 1)) : I(n).notice ? (U(), W("p", Yf, k(I(n).notice), 1)) : J("", !0)]));
	}
}, Zf = ".workspace-main.nx-plugin-full{padding:0!important}.workspace-main.nx-plugin-full>.thread-header[data-full-area-header]{display:none}.workspace-main.nx-plugin-full .split-plugin-page{border-radius:0}.workspace-main.nx-plugin-full .split-content-toolbar{display:none}.workspace-main.nx-plugin-full .split-plugin-page__host{padding:0}.workspace-main.nx-plugin-full .plugin-page-instance,.workspace-main.nx-plugin-full .nx-mount{height:100%;min-height:0}.nx-host>.split-content-toolbar{display:none}.nx-host>.split-plugin-page__host{padding:0}.nx-mount{height:min(780px,76vh);min-height:420px}.nx-host .nx-mount{height:100%;min-height:360px}.nx-mount--quick{height:auto!important;min-height:0!important}.nx-app{--nx-bg:var(--theme-main-background,#111416);--nx-rail:color-mix(in srgb, var(--theme-main-background,#111416) 86%, var(--theme-main-text,#e8eeeb));--nx-panel:color-mix(in srgb, var(--theme-main-background,#111416) 92%, var(--theme-main-text,#e8eeeb));--nx-panel-hover:color-mix(in srgb, var(--theme-main-background,#111416) 84%, var(--theme-main-text,#e8eeeb));--nx-input:color-mix(in srgb, var(--theme-main-background,#111416) 78%, var(--theme-main-text,#e8eeeb));--nx-text:var(--theme-main-text,#e8eeeb);--nx-muted:color-mix(in srgb, var(--theme-main-text,#e8eeeb) 62%, transparent);--nx-faint:color-mix(in srgb, var(--theme-main-text,#e8eeeb) 42%, transparent);--nx-line:var(--theme-main-border,color-mix(in srgb, var(--theme-main-text,#e8eeeb) 14%, transparent));--nx-accent:var(--green,#8ae6bf);--nx-accent-ink:color-mix(in srgb, var(--green,#8ae6bf) 18%, #000);--nx-error:var(--red,#ef9c9f);--nx-warning:var(--orange,var(--nx-warning));background:var(--nx-bg);width:100%;height:100%;min-height:360px;color:var(--nx-text);font-family:var(--font-sans,Inter, \"Segoe UI\", \"Microsoft YaHei\", sans-serif);text-align:left;border-radius:0;font-size:13px;line-height:1.5;display:flex;overflow:hidden;container:nx-shell/inline-size}.nx-app *{box-sizing:border-box}.nx-app button,.nx-app input,.nx-app select,.nx-app textarea{font:inherit}.nx-app button{cursor:pointer}.nx-app button:disabled{cursor:default;opacity:.42}.nx-app svg{vertical-align:middle;flex-shrink:0}.nx-app h1,.nx-app h2,.nx-app h3,.nx-app p{margin:0}.nx-app h2{letter-spacing:-.015em;font-size:14px;font-weight:600;line-height:1.5}.nx-app h3{font-size:13px;font-weight:600}.nx-app button:focus-visible,.nx-app a:focus-visible{outline:2px solid var(--nx-accent);outline-offset:3px}.nx-app input:focus-visible,.nx-app textarea:focus-visible,.nx-app select:focus-visible{outline:1px solid color-mix(in srgb, var(--nx-accent) 65%, transparent);outline-offset:1px}.nx-app ::selection{color:var(--nx-text);background:#315846}.nx-sidebar{background:var(--nx-rail);border-right:1px solid var(--nx-line);flex-direction:column;flex:0 0 88px;align-items:stretch;width:88px;padding:22px 12px 16px;display:flex}.nx-brand{color:var(--nx-accent);flex-direction:column;align-items:center;gap:7px;padding-bottom:24px;display:flex}.nx-brand span{letter-spacing:.02em;color:var(--nx-muted);font-size:10px;font-weight:550}.nx-sidebar nav{flex-direction:column;flex:1;gap:5px;min-height:0;display:flex;overflow-y:auto}.nx-nav-item{min-height:53px;color:var(--nx-muted);background:0 0;border:0;border-radius:11px;flex-direction:column;justify-content:center;align-items:center;gap:5px;transition:background .16s,color .16s;display:flex;position:relative}.nx-nav-item span{font-size:11px}.nx-nav-item:hover{background:color-mix(in srgb, var(--nx-text) 6%, transparent);color:var(--nx-text)}.nx-nav-item.is-active{background:color-mix(in srgb, var(--nx-accent) 11%, transparent);color:var(--nx-accent)}.nx-nav-item.is-active:before{content:\"\";background:var(--nx-accent);border-radius:2px;width:2px;position:absolute;top:13px;bottom:13px;left:0}.nx-nav-divider{background:var(--nx-line);height:1px;margin:14px 8px}.nx-sidebar-foot{color:var(--nx-faint);justify-content:center;align-items:center;gap:6px;margin-top:auto;padding-top:26px;font-size:10px;display:flex}.nx-live-dot{background:var(--nx-accent);border-radius:50%;flex:none;width:6px;height:6px;display:inline-block}.nx-live-dot.is-offline{background:var(--nx-faint)}.nx-workspace{flex-direction:column;flex:1;min-width:0;display:flex;overflow:hidden}.nx-header{border-bottom:1px solid var(--nx-line);flex-shrink:0;justify-content:space-between;align-items:center;gap:16px;padding:22px 30px 18px;display:flex}.nx-header h1{letter-spacing:-.035em;font-size:25px;font-weight:620;line-height:1.3}.nx-header p{color:var(--nx-faint);margin-top:5px;font-size:12px}.nx-header-actions{align-items:center;gap:15px;display:flex}.nx-live-label{color:var(--nx-muted);align-items:center;gap:7px;font-size:11px;display:flex}.nx-working{color:var(--nx-muted);font-size:12px}.nx-content{flex:1;min-height:0;padding:20px 30px 30px;overflow:auto}.nx-content>*{width:100%;min-width:0;max-width:1180px;margin-inline:auto}.nx-eyebrow{color:var(--nx-faint);letter-spacing:.18em;margin-bottom:6px;font-size:9px;font-weight:600;display:block}.nx-page-enter-active,.nx-page-leave-active{transition:opacity .18s,transform .18s}.nx-page-enter-from{opacity:0;transform:translateY(6px)}.nx-page-leave-to{opacity:0;transform:translateY(-4px)}.nx-home{flex-direction:column;gap:16px;display:flex}.nx-stat-bar{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:16px;grid-template-columns:repeat(4,minmax(0,1fr));display:grid;overflow:hidden}.nx-stat{flex-direction:column;gap:5px;min-width:0;padding:15px 20px;display:flex}.nx-stat+.nx-stat{border-left:1px solid var(--nx-line)}.nx-stat>span{color:var(--nx-muted);align-items:center;gap:6px;font-size:11px;display:flex}.nx-stat>strong{font-variant-numeric:tabular-nums;letter-spacing:-.025em;text-overflow:ellipsis;white-space:nowrap;font-size:20px;font-weight:600;overflow:hidden}.nx-stat[data-stat=download]>strong{color:var(--nx-accent)}.nx-home-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;display:grid}.nx-quick-card{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:18px;flex-direction:column;gap:15px;min-height:236px;padding:20px;transition:border-color .18s;display:flex}.nx-quick-card.is-on{border-color:color-mix(in srgb, var(--nx-accent) 34%, var(--nx-line))}.nx-quick-head{align-items:center;gap:10px;min-width:0;display:flex}.nx-quick-icon{background:var(--nx-input);width:38px;height:38px;color:var(--nx-muted);border-radius:12px;flex:0 0 38px;place-items:center;display:grid}.nx-route-icon{background:color-mix(in srgb, var(--nx-accent) 12%, transparent);width:38px;height:38px;color:var(--nx-accent);border-radius:12px;flex:0 0 38px;place-items:center;display:grid}.nx-quick-card.is-on .nx-quick-icon{background:color-mix(in srgb, var(--nx-accent) 14%, transparent);color:var(--nx-accent)}.nx-quick-title{flex:1;min-width:0}.nx-quick-title h2{font-size:14px}.nx-quick-title p{color:var(--nx-faint);margin-top:1px;font-size:10px}.nx-quick-state{border:1px solid var(--nx-line);color:var(--nx-muted);white-space:nowrap;border-radius:999px;padding:3px 8px;font-size:10px}.nx-quick-state.is-live{background:color-mix(in srgb, var(--nx-accent) 14%, transparent);color:var(--nx-accent);border-color:#0000}.nx-quick-main{flex-direction:column;gap:3px;min-width:0;display:flex}.nx-quick-main>strong{letter-spacing:-.02em;text-overflow:ellipsis;white-space:nowrap;font-size:16px;font-weight:600;overflow:hidden}.nx-quick-main>p{color:var(--nx-muted);text-overflow:ellipsis;white-space:nowrap;font-size:11px;overflow:hidden}.nx-quick-actions{align-items:center;gap:8px;margin-top:auto;display:flex}.nx-quick-actions>.nx-button:first-child{flex:1;min-height:38px}.nx-quick-link{color:var(--nx-muted);gap:3px;padding-inline:8px;font-size:11px}.nx-quick-actions--stack{flex-direction:column;align-items:stretch;gap:6px}.nx-home-download{gap:8px;min-width:0;display:flex}.nx-home-download>.nx-input{flex:1;min-width:0;min-height:38px}.nx-home-download>.nx-button{justify-content:center;width:40px;min-height:38px;padding:0}.nx-home-download+.nx-quick-link{align-self:flex-start}.nx-kicker{color:var(--nx-faint);letter-spacing:.16em;font-size:9px;font-weight:600;display:block}.nx-proxy-top{grid-template-columns:minmax(0,1.2fr) minmax(240px,.8fr);gap:14px;display:grid}.nx-subscribe-summary{flex-direction:column;align-items:flex-start;gap:13px;display:flex}.nx-subscribe-copy h3{letter-spacing:-.02em;margin-top:6px;font-size:18px;font-weight:600}.nx-subscribe-copy p{max-width:52ch;color:var(--nx-muted);margin-top:5px;font-size:12px}.nx-subscribe-summary>.nx-button{margin-top:auto}.nx-proxy-connection{flex-direction:column;gap:14px;display:flex}.nx-proxy-connection-row{align-items:center;gap:12px;display:flex}.nx-proxy-connection-row .nx-control-copy{flex:1;min-width:0}.nx-proxy-connection-row .nx-control-copy strong{font-size:14px;font-weight:600}.nx-proxy-connection-row .nx-control-copy p{color:var(--nx-muted);margin-top:3px;font-size:11px}.nx-accel-page{flex-direction:column;gap:20px;display:flex}.nx-accel-control{border:1px solid var(--nx-line);background:radial-gradient(90% 180% at 0% 50%, color-mix(in srgb, var(--nx-accent) 13%, transparent), transparent 60%), var(--nx-panel);border-radius:20px;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:0 20px;padding:26px 28px;display:grid;position:relative;overflow:hidden}.nx-accel-control.is-on{border-color:color-mix(in srgb, var(--nx-accent) 38%, var(--nx-line))}.nx-accel-orb{border:1px solid var(--nx-line);background:var(--nx-input);width:58px;height:58px;color:var(--nx-muted);border-radius:18px;flex:0 0 58px;grid-row:1/span 2;place-items:center;display:grid}.nx-accel-control.is-on .nx-accel-orb{background:var(--nx-accent);color:var(--nx-accent-ink);box-shadow:0 0 0 6px color-mix(in srgb, var(--nx-accent) 14%, transparent);border-color:#0000}.nx-accel-copy{min-width:0}.nx-accel-copy h2{letter-spacing:-.03em;margin-top:5px;font-size:28px;font-weight:650}.nx-accel-copy p{max-width:62ch;color:var(--nx-muted);margin-top:4px;font-size:12px}.nx-accel-control>.nx-button{grid-column:2;justify-self:start;margin-top:14px}.nx-button.nx-large{white-space:nowrap;min-height:46px;padding-inline:24px;font-size:14px}.nx-accel-grid{grid-template-columns:minmax(0,1.45fr) minmax(280px,.85fr);align-items:stretch;gap:20px;display:grid}.nx-accel-facts{flex-direction:column;gap:14px;display:flex}.nx-fact{border-bottom:1px solid var(--nx-line);justify-content:space-between;align-items:center;gap:16px;padding-bottom:13px;display:flex}.nx-fact>span{color:var(--nx-muted);font-size:11px}.nx-fact>strong{text-align:right;font-size:12px;font-weight:550}.nx-fact-link{color:var(--nx-accent);gap:4px;padding:0;font-size:11px}.nx-accel-facts .nx-help{margin-top:auto}.nx-accel-lower{grid-template-columns:minmax(0,1.2fr) minmax(300px,.8fr);align-items:start;gap:20px;display:grid}.nx-accel-lower.nx-single{grid-template-columns:minmax(0,1fr)}.nx-view-stack,.nx-dashboard{gap:20px;min-width:0;display:grid}.nx-dashboard-grid{grid-template-columns:minmax(0,1.75fr) minmax(218px,1fr);align-items:start;gap:20px;display:grid}.nx-dashboard-main,.nx-dashboard-side{gap:20px;min-width:0;display:grid}.nx-dashboard-hero{grid-template-columns:minmax(0,1.8fr) minmax(238px,.95fr);align-items:stretch}.nx-dashboard-tiles{grid-template-columns:minmax(0,1.35fr) minmax(185px,.82fr) minmax(190px,.9fr)}.nx-dashboard-lower{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);align-items:start;gap:20px;display:grid}.nx-accelerate-card{flex-direction:column;display:flex}.nx-switch-row{justify-content:space-between;align-items:center;gap:16px;display:flex}.nx-switch-row strong{font-size:13px;font-weight:550}.nx-switch-row p{color:var(--nx-muted);overflow-wrap:anywhere;margin-top:4px;font-size:11px}.nx-accelerate-card>.nx-help{color:var(--nx-faint);margin-top:15px;font-size:10px}.nx-accelerate-state{color:var(--nx-muted);overflow-wrap:anywhere;margin-top:4px;font-size:12px}.nx-accelerate-card .nx-block{width:100%;min-height:44px;margin-top:15px;font-size:14px}.nx-line-card{flex-direction:column;display:flex}.nx-line-current{align-items:baseline;gap:10px;min-width:0;display:flex}.nx-line-current strong{letter-spacing:-.02em;overflow-wrap:anywhere;font-size:22px;font-weight:600}.nx-line-delay{color:var(--nx-accent);font-variant-numeric:tabular-nums;white-space:nowrap;font-size:12px}.nx-line-meta{color:var(--nx-faint);flex-wrap:wrap;gap:4px 12px;margin-top:5px;font-size:11px;display:flex}.nx-line-actions{flex-wrap:wrap;align-items:center;gap:10px;margin-top:auto;padding-top:17px;display:flex}.nx-line-select select{max-width:150px}.nx-line-actions .nx-button{margin-left:auto}.nx-line-off{flex-direction:column;align-items:flex-start;gap:12px;display:flex}.nx-line-off p{color:var(--nx-muted);font-size:12px}.nx-donut-row{align-items:center;gap:18px;display:flex}.nx-donut{border-radius:50%;flex:0 0 78px;place-items:center;width:78px;height:78px;display:grid;position:relative}.nx-donut:after{content:\"\";background:var(--nx-panel);border-radius:50%;position:absolute;inset:9px}.nx-donut span{z-index:1;color:var(--nx-muted);font-variant-numeric:tabular-nums;font-size:12px;position:relative}.nx-traffic-legend{flex-direction:column;gap:10px;min-width:0;display:flex}.nx-traffic-legend>div{flex-direction:column;gap:2px;display:flex}.nx-traffic-legend span{color:var(--nx-muted);align-items:center;gap:5px;font-size:11px;display:flex}.nx-traffic-legend strong{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;font-size:13px;font-weight:500}.nx-legend-down svg{color:var(--nx-accent)}.nx-legend-up svg{color:#8f9a94}.nx-traffic-card>.nx-help{color:var(--nx-faint);margin-top:15px;font-size:10px}.nx-two-columns{grid-template-columns:minmax(0,1.55fr) minmax(230px,1fr);align-items:start;gap:20px;display:grid}.nx-panel{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:16px;min-width:0;padding:20px}.nx-panel-heading{justify-content:space-between;align-items:center;gap:10px;min-height:22px;margin-bottom:16px;display:flex}.nx-panel-heading>div{min-width:0}.nx-panel-heading .nx-kicker+h2{margin-top:4px}.nx-panel-heading h2{color:var(--nx-text);align-items:center;gap:9px;display:flex}.nx-panel-heading h2>svg{color:var(--nx-muted)}.nx-section-heading{justify-content:space-between;align-items:center;gap:16px;display:flex}.nx-section-heading p{color:var(--nx-muted);margin-top:5px;font-size:12px}.nx-subtle,.nx-help{color:var(--nx-muted);font-size:12px}.nx-help{max-width:70ch;line-height:1.7}.nx-panel>.nx-help+.nx-button{margin-top:14px}.nx-empty-inline{color:var(--nx-faint);padding:20px 0 6px;font-size:12px}.nx-button{appearance:none;min-height:34px;color:var(--nx-text);white-space:nowrap;background:0 0;border:1px solid #0000;border-radius:9px;justify-content:center;align-items:center;gap:7px;padding:7px 12px;font-size:12px;font-weight:550;line-height:1.4;transition:background .15s,border-color .15s,color .15s;display:inline-flex}.nx-button svg{stroke-width:1.7px}.nx-primary{background:var(--nx-accent);color:var(--nx-accent-ink);border-color:var(--nx-accent)}.nx-primary:hover:not(:disabled){filter:brightness(.94)}.nx-primary:active:not(:disabled){filter:brightness(.88)}.nx-secondary{color:#dae8df;background:#252d29;border-color:#37463d}.nx-secondary:hover:not(:disabled){background:#303d35;border-color:#4b6053}.nx-quiet{color:var(--nx-muted);font-weight:450}.nx-quiet:hover:not(:disabled){background:color-mix(in srgb, var(--nx-text) 7%, transparent);color:var(--nx-text)}.nx-icon-button{min-width:32px;min-height:32px;padding:6px}.nx-danger-text{color:var(--nx-error)}.nx-actions{flex-wrap:wrap;align-items:center;gap:8px;display:flex}.nx-switch{border:1px solid var(--nx-line);background:var(--nx-input);border-radius:99px;flex:0 0 44px;width:44px;height:25px;padding:3px;transition:background .18s,border-color .18s;position:relative}.nx-switch>span{background:var(--nx-muted);border-radius:50%;width:17px;height:17px;transition:transform .18s,background .18s;display:block;transform:translate(0)}.nx-switch[aria-checked=true]{background:var(--nx-accent);border-color:var(--nx-accent)}.nx-switch[aria-checked=true]>span{background:#193b2a;transform:translate(18px)}.nx-switch--small{transform-origin:0;margin-right:-6px;transform:scale(.86)}.nx-notice{background:color-mix(in srgb, var(--nx-accent) 9%, var(--nx-panel));color:var(--nx-text);border:1px solid var(--nx-line);border-radius:10px;flex-shrink:0;justify-content:space-between;align-items:center;gap:12px;margin:0 30px 18px;padding:10px 12px;font-size:12px;display:flex}.nx-notice--error{color:var(--nx-error);background:#2e2023;border-color:#4b3037}.nx-notice>span{overflow-wrap:anywhere;min-width:0}.nx-notice .nx-button{color:inherit;flex-shrink:0}.nx-acceleration{background:color-mix(in srgb, var(--nx-accent) 7%, var(--nx-panel));align-items:center;gap:17px;padding:23px 24px;display:flex}.nx-acceleration-icon{background:color-mix(in srgb, var(--nx-accent) 10%, var(--nx-panel));width:52px;height:52px;color:var(--nx-muted);border-radius:16px;flex:0 0 52px;place-items:center;display:grid}.nx-acceleration-icon.is-on{color:var(--nx-accent);background:#294d3a}.nx-acceleration-copy{flex:1;min-width:0}.nx-acceleration-copy h2{align-items:center;gap:10px;font-size:17px;font-weight:600;display:flex}.nx-acceleration-copy p{color:var(--nx-muted);overflow-wrap:anywhere;margin-top:6px;font-size:12px}.nx-badge{border:1px solid var(--nx-line);color:var(--nx-muted);white-space:nowrap;border-radius:6px;padding:2px 7px;font-size:10px;font-weight:450}.nx-badge.is-on{color:var(--nx-accent);background:#233a2d;border-color:#3e5c4a}.nx-acceleration>.nx-button{min-height:39px;padding-inline:16px}.nx-node-toolbar{justify-content:space-between;align-items:center;gap:12px;margin:-2px 0 10px;display:flex}.nx-optimize{white-space:nowrap;margin-left:auto}.nx-node-head-actions{align-items:center;gap:6px;display:flex}.nx-line-groups{flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:12px;display:flex}.nx-line-group{border:1px solid var(--nx-line);color:var(--nx-muted);background:0 0;border-radius:999px;padding:6px 12px;font-size:11px;transition:background .16s,border-color .16s,color .16s}.nx-line-group:hover{background:var(--nx-panel-hover);color:var(--nx-text)}.nx-line-group.is-active{border-color:color-mix(in srgb, var(--nx-accent) 42%, var(--nx-line));background:color-mix(in srgb, var(--nx-accent) 10%, transparent);color:var(--nx-text)}.nx-line-groups .nx-subtle{margin-left:auto}.nx-line-list{flex-direction:column;max-height:430px;margin:0 -8px;display:flex;overflow:auto}.nx-line-row{border-bottom:1px solid var(--nx-line);align-items:center;gap:6px;display:flex}.nx-line-row:last-child{border-bottom:0}.nx-line-choice{min-width:0;color:var(--nx-text);text-align:left;background:0 0;border:0;border-radius:10px;flex:1;align-items:center;gap:12px;padding:13px 8px;display:flex}.nx-line-choice:hover{background:var(--nx-panel-hover)}.nx-line-row.is-selected .nx-line-choice{background:color-mix(in srgb, var(--nx-accent) 7%, transparent)}.nx-line-radio{border:1px solid var(--nx-line);width:16px;height:16px;color:var(--nx-accent-ink);border-radius:50%;flex:0 0 16px;place-items:center;display:grid}.nx-line-row.is-selected .nx-line-radio{border-color:var(--nx-accent);background:var(--nx-accent)}.nx-line-name{text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;font-size:13px;overflow:hidden}.nx-line-meter{background:var(--nx-line);border-radius:999px;flex:0 0 120px;width:120px;height:4px;overflow:hidden}.nx-line-meter i{border-radius:inherit;background:var(--nx-accent);height:100%;transition:width .3s;display:block}.nx-line-meter.is-mid i{background:var(--nx-warning)}.nx-line-meter.is-slow i{background:var(--nx-error)}.nx-line-meter.is-unknown i{background:var(--nx-faint)}.nx-line-ms{width:62px;color:var(--nx-muted);font-variant-numeric:tabular-nums;text-align:right;flex:0 0 62px;font-size:11px}.nx-line-refresh{opacity:.35}.nx-line-row:hover .nx-line-refresh,.nx-line-row.is-selected .nx-line-refresh{opacity:1}.nx-node-list{max-height:380px;margin-inline:-8px;overflow:auto}.nx-node-list--compact{max-height:206px}.nx-node{border-radius:9px;align-items:center;min-width:0;display:flex}.nx-node:hover{background:color-mix(in srgb, var(--nx-text) 4%, transparent)}.nx-node.is-selected{background:#25352b}.nx-node-choice{text-align:left;width:100%;min-width:0;min-height:43px;color:var(--nx-text);background:0 0;border:0;border-radius:9px;align-items:center;gap:11px;padding:10px 9px;display:flex}.nx-node-name{text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:13px;overflow:hidden}.nx-node-delay{color:var(--nx-faint);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:11px}.is-selected .nx-node-delay{color:#91b69e}.nx-radio-mark{border:1px solid #4d5a52;border-radius:50%;flex-shrink:0;place-items:center;width:16px;height:16px;display:grid}.is-selected .nx-radio-mark{background:var(--nx-accent);border-color:var(--nx-accent);color:var(--nx-accent-ink)}.nx-node-search{margin-bottom:10px}.nx-add-profile{margin-top:13px;padding-inline:4px;font-size:11px}.nx-select-wrap{align-items:center;gap:6px;min-width:0;display:flex;position:relative}.nx-select-wrap select{appearance:none;color:var(--nx-text);outline-offset:3px;cursor:pointer;background:0 0;border:0;max-width:220px;padding:1px 20px 1px 0;font-size:12px}.nx-select-wrap svg{pointer-events:none;color:var(--nx-faint);position:absolute;right:0}.nx-select-wrap option{background:var(--nx-panel);color:var(--nx-text)}.nx-speed{flex-direction:column;padding-bottom:15px;display:flex}.nx-speed-values{flex-wrap:wrap;gap:30px;margin-top:3px;display:flex}.nx-speed-values>span{align-items:center;gap:7px;min-width:0;display:flex}.nx-speed-values strong{letter-spacing:-.025em;font-variant-numeric:tabular-nums;font-size:19px;font-weight:550}.nx-speed-values small{color:var(--nx-faint);padding-top:4px;font-size:10px}.nx-speed-values>span:first-child>svg{color:var(--nx-accent)}.nx-speed-values>span:nth-child(2)>svg{color:var(--blue,#a2b8c6)}.nx-plot{min-height:153px;color:var(--nx-accent);flex:1;margin:17px -6px 0}.nx-plot>svg{width:100%;height:100%;overflow:visible}.nx-chart-grid{stroke:var(--nx-line);stroke-width:1px;fill:none;vector-effect:non-scaling-stroke}.nx-chart-area{stroke:none}.nx-chart-download{stroke:var(--nx-accent);stroke-width:2px;stroke-linejoin:round;stroke-linecap:round;fill:none;vector-effect:non-scaling-stroke}.nx-chart-upload{stroke:var(--blue,#8a9ca5);stroke-width:1.5px;stroke-dasharray:4 5;fill:none;vector-effect:non-scaling-stroke;opacity:.65}.nx-chart-axis{color:var(--nx-faint);justify-content:space-between;gap:10px;margin-top:8px;font-size:10px;display:flex}.nx-chart-wait{height:100%;color:var(--nx-faint);flex-direction:column;justify-content:center;align-items:center;gap:6px;font-size:12px;display:flex}.nx-chart-wait small{color:var(--nx-faint);font-size:11px}.nx-mode-options{flex-direction:column;gap:5px;display:flex}.nx-mode{width:100%;color:var(--nx-muted);text-align:left;background:0 0;border:1px solid #0000;border-radius:10px;align-items:center;gap:11px;min-width:0;padding:10px 8px;display:flex}.nx-mode:hover:not(:disabled){background:var(--nx-line)}.nx-mode[aria-checked=true]{color:var(--nx-text);background:#28372d;border-color:#3d5143}.nx-mode>span:nth-child(2){flex:1;gap:3px;min-width:0;display:grid}.nx-mode strong{font-size:12px;font-weight:550}.nx-mode small{color:var(--nx-faint);font-size:10px;line-height:1.5}.nx-mode-dot{border:1px solid #5c6c61;border-radius:50%;flex-shrink:0;width:13px;height:13px}.nx-mode[aria-checked=true] .nx-mode-dot{border:4px solid var(--nx-accent)}.nx-modes>.nx-help{margin-top:10px;font-size:11px}.nx-local-info>strong{color:var(--nx-muted);font-size:12px;font-weight:500}.nx-address{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;letter-spacing:-.015em;margin:7px 0 10px;font-size:18px;font-weight:500}.nx-local-info>.nx-button{padding-left:0;font-size:11px}.nx-total>div:not(.nx-panel-heading){justify-content:space-between;align-items:center;gap:12px;margin-top:11px;display:flex}.nx-total>div>span{color:var(--nx-muted);align-items:center;gap:6px;font-size:12px;display:flex}.nx-total strong{font-variant-numeric:tabular-nums;font-size:14px;font-weight:500}.nx-total>.nx-help{color:var(--nx-faint);margin-top:15px;font-size:10px}.nx-input{border:1px solid var(--nx-line);background:var(--nx-input);width:100%;min-width:0;min-height:38px;color:var(--nx-text);accent-color:var(--nx-accent);border-radius:9px;padding:9px 12px;font-size:12px;line-height:1.5}.nx-input::placeholder{color:#839188;opacity:1}.nx-input option{background:var(--nx-panel);color:var(--nx-text)}.nx-inline-form{align-items:center;gap:10px;min-width:0;display:flex}.nx-inline-form>.nx-input{flex:1}.nx-inline-form>.nx-button{flex-shrink:0;min-height:38px}.nx-input-with-icon,.nx-input-with-action{flex:1;align-items:center;min-width:0;display:flex;position:relative}.nx-input-with-icon>svg{color:var(--nx-faint);pointer-events:none;position:absolute;left:12px}.nx-input-with-icon>.nx-input{padding-left:38px}.nx-input-with-action>.nx-input{padding-right:42px}.nx-input-with-action>.nx-button{position:absolute;right:4px}.nx-fit-select{min-width:100px;flex:0 auto!important;width:auto!important}.nx-form{gap:15px;display:grid}.nx-form>.nx-button{justify-self:start}.nx-form-grid{grid-template-columns:1fr 1fr;gap:16px;display:grid}.nx-form-grid>label{gap:7px;min-width:0;display:grid}.nx-form-grid>label>span{color:var(--nx-muted);font-size:12px}.nx-code{resize:vertical;font-family:Cascadia Code,Consolas,monospace;font-size:12px;line-height:1.7}.nx-import>.nx-help{margin-bottom:13px}.nx-import-options{flex-wrap:wrap;gap:14px;margin-top:8px;display:flex}.nx-import-options>.nx-button{padding-left:0;font-size:11px}.nx-import>.nx-form{margin-top:12px}.nx-import-running{justify-content:space-between;align-items:center;gap:12px;margin-top:14px;display:flex}.nx-import-running .nx-button{font-size:11px}.nx-import>.nx-help:last-child{margin-top:12px;margin-bottom:0}.nx-site-shortcuts{flex-wrap:wrap;align-items:center;gap:4px;margin-top:8px;display:flex}.nx-site-shortcuts>span{color:var(--nx-faint);margin-right:4px;font-size:10px}.nx-site-shortcuts .nx-button{min-height:27px;padding:4px 6px;font-size:10px}.nx-recent{padding:18px 20px}.nx-recent>.nx-section-heading{margin-bottom:9px}.nx-event{border-bottom:1px solid #252e28;align-items:center;gap:11px;padding:11px 0;font-size:12px;display:flex}.nx-event>svg{color:var(--nx-faint)}.nx-event>span{overflow-wrap:anywhere;flex:1;min-width:0}.nx-event>time{color:var(--nx-faint);white-space:nowrap;font-size:10px}.nx-event:last-child{border-bottom:0;padding-bottom:0}.nx-empty{text-align:center;color:var(--nx-faint);flex-direction:column;justify-content:center;align-items:center;gap:11px;padding:52px 20px;display:flex}.nx-empty>svg{color:#83968a;margin-bottom:3px}.nx-empty>strong{color:var(--nx-text);font-size:14px;font-weight:500}.nx-empty>p{max-width:35ch;color:var(--nx-muted);font-size:12px;line-height:1.7}.nx-empty>.nx-button{margin-top:5px}.nx-empty--small{padding:27px 10px}.nx-empty--small strong{font-size:12px}.nx-empty--small p{font-size:11px}.nx-control-row{align-items:center;gap:15px;display:flex}.nx-control-row--plain{padding:0}.nx-control-icon{color:#bfd0c4;background:#28322b;border-radius:11px;flex:0 0 40px;place-items:center;width:40px;height:40px;display:grid}.nx-control-copy{flex:1;min-width:0}.nx-control-copy strong{font-size:13px;font-weight:550}.nx-control-copy p{color:var(--nx-muted);margin-top:4px;font-size:11px;line-height:1.6}.nx-settings-fold{padding-top:3px}.nx-settings-fold>.nx-panel{margin-top:12px}.nx-detail-list{max-width:650px;margin:12px 0}.nx-detail-list>div{border-bottom:1px solid var(--nx-line);color:var(--nx-muted);justify-content:space-between;gap:15px;padding:10px 0;font-size:12px;display:flex}.nx-detail-list>div>span:last-child{align-items:center;gap:5px;display:flex}.nx-detail-list code{color:var(--nx-text);font-size:11px}.nx-download-composer>.nx-inline-form{margin-bottom:5px}.nx-download-stats{border:1px solid var(--nx-line);background:var(--nx-panel);border-radius:14px;grid-template-columns:repeat(3,minmax(0,1fr));display:grid;overflow:hidden}.nx-download-stats>div{justify-content:space-between;align-items:baseline;gap:10px;padding:12px 18px;display:flex}.nx-download-stats>div+div{border-left:1px solid var(--nx-line)}.nx-download-stats span{color:var(--nx-muted);font-size:11px}.nx-download-stats strong{font-variant-numeric:tabular-nums;font-size:15px;font-weight:600}.nx-download-composer.is-dragging{border-color:color-mix(in srgb, var(--nx-accent) 55%, var(--nx-line));background:color-mix(in srgb, var(--nx-accent) 7%, var(--nx-panel))}.nx-download-options{flex-wrap:wrap;gap:8px 18px;margin:9px 0 4px;display:flex}.nx-download-options>label{color:var(--nx-muted);align-items:center;gap:8px;font-size:11px;display:flex}.nx-download-options select{border:1px solid var(--nx-line);background:var(--nx-input);min-height:30px;color:var(--nx-text);border-radius:8px;padding:4px 8px;font-size:11px}.nx-options-button{padding-left:0;font-size:11px}.nx-download-composer>.nx-form-grid{padding-top:13px}.nx-checkbox{align-self:end;align-items:center;min-height:38px;gap:8px!important;display:flex!important}.nx-checkbox>input{accent-color:var(--nx-accent)}.nx-list-toolbar{justify-content:space-between;align-items:center;gap:12px;display:flex}.nx-filter-tabs{align-items:center;gap:5px;display:flex}.nx-filter-tabs>button{min-height:32px;color:var(--nx-muted);background:0 0;border:0;border-radius:8px;align-items:center;gap:7px;padding:6px 10px;font-size:12px;display:flex}.nx-filter-tabs>button.active{color:var(--nx-text);background:#29332c}.nx-filter-tabs>button:hover{background:#242e27}.nx-filter-tabs>button>span{color:var(--nx-faint);font-size:10px}.nx-task-list{padding:0 20px}.nx-download-row{border-bottom:1px solid var(--nx-line);grid-template-columns:40px minmax(0,1fr) auto;align-items:center;column-gap:15px;padding:23px 0;display:grid}.nx-download-row:last-child{border-bottom:0}.nx-file-icon{color:#b3d5bd;background:#29352c;border-radius:10px;place-items:center;width:40px;height:45px;display:grid}.nx-download-body{min-width:0}.nx-task-title{justify-content:space-between;align-items:baseline;gap:12px;min-width:0;display:flex}.nx-task-title>strong{text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:500;overflow:hidden}.nx-task-title>span{color:var(--nx-muted);white-space:nowrap;font-size:10px}.nx-progress-track{background:#313b34;border-radius:99px;height:4px;margin:10px 0 8px;overflow:hidden}.nx-progress-track>span{background:var(--nx-accent);border-radius:inherit;height:100%;transition:width .25s;display:block}.nx-task-meta{color:var(--nx-faint);font-variant-numeric:tabular-nums;flex-wrap:wrap;justify-content:space-between;gap:10px;font-size:10px;display:flex}.nx-meta-divider{color:var(--nx-faint);margin-inline:6px}.nx-task-controls{align-items:center;gap:5px;display:flex}.nx-task-details{grid-column:2/-1;gap:13px;padding:17px 0 0;display:grid}.nx-task-details>.nx-subtle{overflow-wrap:anywhere;font-size:11px}.nx-small-select{color:var(--nx-muted);align-items:center;gap:8px;font-size:11px;display:flex}.nx-small-select select{background:var(--nx-input);border:1px solid var(--nx-line);min-height:30px;color:var(--nx-text);border-radius:7px;padding:4px 7px}.nx-state-error{color:var(--nx-error)!important}.nx-diagnose-start{text-align:center;padding:30px 28px 23px}.nx-diagnose-symbol{width:49px;height:49px;color:var(--nx-accent);background:#2a3d30;border-radius:15px;place-items:center;margin:0 auto 15px;display:grid}.nx-diagnose-start>h2{letter-spacing:-.025em;font-size:19px;font-weight:550}.nx-diagnose-start>p{color:var(--nx-muted);margin-top:7px;font-size:12px}.nx-diagnose-start>.nx-inline-form{max-width:580px;margin:22px auto 0}.nx-diagnose-options{color:var(--nx-muted);flex-wrap:wrap;justify-content:center;align-items:center;gap:20px;margin-top:17px;font-size:11px;display:flex}.nx-diagnose-options>label{cursor:pointer;align-items:center;gap:5px;display:flex}.nx-diagnose-options input{accent-color:var(--nx-accent);width:12px;height:12px;margin:0}.nx-report-heading{align-items:center;gap:14px;margin-bottom:20px;display:flex}.nx-result-icon{width:44px;height:44px;color:var(--nx-accent);background:#273f2f;border-radius:13px;place-items:center;display:grid}.nx-result-icon.is-failure{color:var(--nx-warning);background:#3c3324}.nx-report-heading h2{font-size:16px}.nx-report-heading p{color:var(--nx-muted);margin-top:4px;font-size:11px}.nx-check-list{gap:0;display:grid}.nx-check-row{border-bottom:1px solid var(--nx-line);grid-template-columns:20px minmax(0,1fr) auto 66px;align-items:center;gap:11px;min-height:47px;display:grid}.nx-check-row:last-child{border-bottom:0}.nx-check-status{width:18px;height:18px;color:var(--nx-accent);border:1px solid #3f5b49;border-radius:50%;place-items:center;display:grid}.nx-check-status.is-failure{color:var(--nx-error);border-color:#70504d}.nx-check-row strong{font-size:12px;font-weight:450}.nx-check-row>span:not(.nx-check-status){color:var(--nx-muted);font-size:11px}.nx-check-row time{color:var(--nx-faint);text-align:right;font-variant-numeric:tabular-nums;font-size:11px}.nx-report-advice{color:var(--nx-muted);font-size:12px;line-height:1.8;margin-top:17px!important}.nx-report-detail-button{margin-top:10px;padding-left:0;font-size:11px}.nx-check-evidence{gap:14px;margin-top:10px;display:grid}.nx-check-evidence>div{background:var(--nx-input);border-radius:9px;min-width:0;padding:12px}.nx-check-evidence strong{color:var(--nx-muted);font-size:11px;font-weight:500}.nx-check-evidence p{overflow-wrap:anywhere;white-space:pre-wrap;color:var(--nx-faint);margin-top:6px;font-size:11px;line-height:1.7}.nx-history>.nx-section-heading{padding-bottom:10px}.nx-history-row{border:0;border-bottom:1px solid var(--nx-line);text-align:left;width:100%;color:var(--nx-text);background:0 0;align-items:center;gap:12px;padding:13px 2px;display:flex}.nx-history-row:hover{background:color-mix(in srgb, var(--nx-text) 3%, transparent)}.nx-history-row>strong{text-overflow:ellipsis;flex:1;min-width:0;font-size:12px;font-weight:500;overflow:hidden}.nx-history-row>span:not(.nx-history-result),.nx-history-row>time{color:var(--nx-faint);font-size:10px}.nx-history-result{color:var(--nx-accent)}.nx-history-result.is-failure{color:var(--nx-warning)}.nx-diagnose-empty{padding-block:28px;font-size:12px}.nx-diagnose-pending>p{color:var(--nx-muted);margin-block:15px;font-size:12px}.nx-skeleton{background:linear-gradient(100deg, var(--nx-line) 20%, #303b33 45%, var(--nx-line) 70%);background-size:220% 100%;border-radius:8px;animation:1.6s infinite nx-loading-sheen}.nx-skeleton-title{width:180px;height:15px}.nx-skeleton-row{width:100%;height:35px;margin-block:10px}.nx-loading-banner{height:100px}.nx-loading-grid{grid-template-columns:1.7fr 1fr;gap:20px;margin-top:20px;display:grid}.nx-loading-chart{height:250px}.nx-loading>p{color:var(--nx-muted);margin-top:18px;font-size:12px}.nx-loading>.nx-button{margin-top:14px}.nx-interface-list{padding-block:0}.nx-interface{border-bottom:1px solid var(--nx-line);grid-template-columns:40px minmax(0,1fr);gap:16px;padding:22px 0;display:grid}.nx-interface:last-child{border:0}.nx-interface strong{font-size:13px;font-weight:500}.nx-interface dl{gap:7px;margin:10px 0 0;display:grid}.nx-interface dl>div{gap:18px;min-width:0;font-size:11px;display:flex}.nx-interface dt{min-width:52px;color:var(--nx-faint)}.nx-interface dd{color:var(--nx-muted);overflow-wrap:anywhere;margin:0}.nx-query-result{border-top:1px solid var(--nx-line);padding-top:14px}.nx-query-address{font-variant-numeric:tabular-nums;margin-top:8px;font-size:13px}.nx-rule-row{grid-template-columns:minmax(0,1fr) minmax(100px,.65fr) 30px;gap:8px;display:grid}.nx-table-panel{padding:0;overflow:hidden}.nx-table-scroll{max-width:100%;overflow:auto}.nx-table{border-collapse:collapse;white-space:nowrap;text-align:left;width:100%;font-size:12px}.nx-table th{color:var(--nx-faint);border-bottom:1px solid var(--nx-line);padding:13px 17px;font-size:10px;font-weight:450}.nx-table td{color:var(--nx-muted);border-bottom:1px solid #29312c;padding:14px 17px}.nx-table tr:last-child td{border-bottom:0}.nx-table td strong{color:var(--nx-text);text-overflow:ellipsis;max-width:180px;font-size:12px;font-weight:500;display:block;overflow:hidden}.nx-table td small{color:var(--nx-faint);margin-top:3px;font-size:10px;display:block}.nx-table tbody tr:hover{background:#202822}.nx-table .nx-data-cell{font-variant-numeric:tabular-nums;font-size:11px}.nx-protocol{color:var(--nx-faint);border:1px solid #39433c;border-radius:4px;padding:2px 5px;font-size:10px}.nx-connection-state{color:var(--nx-faint);font-size:11px}.nx-connection-state.is-live{color:#9bc9ac}.nx-table-loading{padding:10px 18px}.nx-load-more{border-top:1px solid var(--nx-line);border-radius:0;width:100%;min-height:39px;font-size:11px}.nx-application-actions{grid-template-columns:1fr 1fr;gap:24px;padding-block:8px;display:grid}.nx-application-actions p{color:var(--nx-muted);margin:6px 0 13px;font-size:11px}.nx-transaction-list>.nx-panel-heading{margin-bottom:5px}.nx-transaction{border-bottom:1px solid var(--nx-line);align-items:center;gap:13px;padding:16px 0;display:flex}.nx-transaction:last-child{border-bottom:0}.nx-transaction-icon{color:var(--nx-faint)}.nx-transaction>div{overflow-wrap:anywhere;flex:1;min-width:0}.nx-transaction strong{font-size:12px;font-weight:500}.nx-transaction p,.nx-transaction small{color:var(--nx-faint);margin-top:3px;font-size:10px;display:block}.nx-status-text{color:var(--nx-muted);white-space:nowrap;font-size:10px}.nx-status-text.is-warning{color:var(--nx-warning)}.nx-schedule-form{margin-top:15px}.nx-schedule-row{border-bottom:1px solid var(--nx-line);align-items:center;gap:12px;padding:15px 0;display:flex}.nx-schedule-row:last-child{border-bottom:0}.nx-schedule-row>div{flex:1;min-width:0}.nx-schedule-row strong{overflow-wrap:anywhere;font-size:12px;font-weight:500}.nx-schedule-row small{color:var(--nx-faint);margin-top:4px;font-size:10px;display:block}.nx-settings-rows{padding-block:0}.nx-settings-rows>div{border-bottom:1px solid var(--nx-line);justify-content:space-between;align-items:center;gap:24px;padding:20px 0;display:flex}.nx-settings-rows>div:last-child{border:0}.nx-settings-rows strong{font-size:12px;font-weight:500;display:block}.nx-settings-rows small{color:var(--nx-muted);margin-top:5px;font-size:11px;display:block}.nx-host .plugin-page-instance{height:100%}.nx-quick-app{--nx-text:var(--theme-backdrop-text,var(--theme-main-text,#e8eeeb));--nx-muted:color-mix(in srgb, var(--nx-text) 60%, transparent);--nx-faint:color-mix(in srgb, var(--nx-text) 40%, transparent);--nx-line:color-mix(in srgb, var(--nx-text) 11%, transparent);--nx-accent:var(--green,#8ae6bf);--nx-accent-ink:color-mix(in srgb, var(--green,#8ae6bf) 18%, #000);--nx-panel:transparent;--nx-panel-hover:color-mix(in srgb, var(--nx-text) 7%, transparent);--nx-input:color-mix(in srgb, var(--nx-text) 5%, transparent);background:0 0;border:0;border-radius:0;width:100%;max-width:100%;height:auto;min-height:0;padding:0;display:block;overflow:visible}.nx-pill-list{flex-direction:column;gap:8px;display:flex}.nx-quick-pill{border:1px solid color-mix(in srgb, var(--nx-text) 9%, transparent);background:color-mix(in srgb, var(--nx-text) 4%, transparent);width:100%;min-height:46px;box-shadow:inset 0 1px 0 color-mix(in srgb, var(--nx-text) 5%, transparent);color:var(--nx-text);border-radius:999px;align-items:center;gap:8px;padding:6px 8px 6px 10px;transition:border-color .16s,background .16s;display:flex}.nx-quick-pill:focus-within{border-color:color-mix(in srgb, var(--nx-accent) 42%, var(--nx-line))}.nx-quick-pill.is-on{border-color:color-mix(in srgb, var(--nx-accent) 30%, transparent);background:color-mix(in srgb, var(--nx-accent) 6%, transparent)}.nx-pill-icon{background:color-mix(in srgb, var(--nx-text) 6%, transparent);width:30px;height:30px;color:var(--nx-muted);border-radius:50%;flex:0 0 30px;place-items:center;display:grid}.nx-quick-pill.is-on .nx-pill-icon{background:color-mix(in srgb, var(--nx-accent) 13%, transparent);color:var(--nx-accent)}.nx-pill-value{min-width:0;color:var(--nx-muted);font-variant-numeric:tabular-nums;letter-spacing:-.01em;flex:1;font-size:11px}.nx-pill-value.is-live{color:var(--nx-accent)}.nx-mini-action{border:1px solid var(--nx-line);width:32px;height:32px;color:var(--nx-muted);background:0 0;border-radius:50%;flex:0 0 32px;place-items:center;padding:0;transition:border-color .16s,background .16s,color .16s;display:grid}.nx-mini-action:hover:not(:disabled){border-color:color-mix(in srgb, var(--nx-accent) 36%, var(--nx-line));color:var(--nx-text)}.nx-mini-action.is-on,.nx-mini-action.is-ready{background:var(--nx-accent);color:var(--nx-accent-ink);border-color:#0000}.nx-mini-action:disabled{opacity:.38}.nx-node-wrap{flex:1;align-items:center;min-width:0;display:flex;position:relative}.nx-node-select{width:100%;min-width:0;height:32px;color:var(--nx-text);text-overflow:ellipsis;appearance:none;cursor:pointer;background:0 0;border:0;padding:0 18px 0 2px;font-size:11px}.nx-node-select:focus{outline:none}.nx-chevron{color:var(--nx-faint);pointer-events:none;position:absolute;right:2px}.nx-download-form{flex:1;align-items:center;gap:6px;min-width:0;display:flex}.nx-download-form>input{min-width:0;height:32px;color:var(--nx-text);background:0 0;border:0;outline:none;flex:1;padding:0 2px;font-size:11px}.nx-download-form>input::placeholder{color:var(--nx-faint)}.nx-quick-error,.nx-quick-note{overflow-wrap:anywhere;font-size:10px;line-height:1.5;margin:8px 4px 0!important}.nx-quick-error{color:var(--nx-error)}.nx-quick-note{color:var(--nx-accent)}@keyframes nx-loading-sheen{to{background-position:-220% 0}}@container nx-shell (width<=850px){.nx-sidebar{flex-basis:76px;width:76px;padding-inline:9px}.nx-header{padding:23px 22px 20px}.nx-content{padding:0 22px 24px}.nx-notice{margin-inline:22px}.nx-panel{padding:17px}.nx-dashboard-grid{grid-template-columns:minmax(0,1.65fr) minmax(205px,1fr);gap:16px}.nx-dashboard-hero{grid-template-columns:minmax(0,1.5fr) minmax(210px,1fr)}.nx-dashboard-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.nx-dashboard-lower{grid-template-columns:minmax(0,1fr)}.nx-stat-bar{grid-template-columns:repeat(2,minmax(0,1fr))}.nx-stat:nth-child(3){border-top:1px solid var(--nx-line);border-left:0}.nx-stat:nth-child(4){border-top:1px solid var(--nx-line)}.nx-home-grid{grid-template-columns:minmax(0,1fr)}.nx-quick-card{min-height:0}.nx-proxy-top{grid-template-columns:minmax(0,1fr)}.nx-accel-control{grid-template-columns:auto minmax(0,1fr)}.nx-accel-control>.nx-button{grid-column:1/-1;width:100%}.nx-accel-grid,.nx-accel-lower{grid-template-columns:minmax(0,1fr)}.nx-dashboard-main,.nx-dashboard-side{gap:16px}.nx-acceleration{gap:13px;padding:19px 20px}.nx-acceleration-copy h2{font-size:16px}.nx-acceleration-icon{border-radius:13px;flex-basis:44px;width:44px;height:44px}.nx-speed-values{gap:19px}.nx-speed-values strong{font-size:17px}.nx-speed-values small{display:none}.nx-two-columns{grid-template-columns:minmax(0,1.4fr) minmax(205px,1fr);gap:16px}.nx-task-list{padding-block:0}.nx-task-meta{font-size:10px}.nx-total strong{font-size:13px}}@container nx-shell (width<=680px){.nx-dashboard-grid,.nx-two-columns{grid-template-columns:minmax(0,1fr)}.nx-line-meter{display:none}.nx-download-stats{grid-template-columns:minmax(0,1fr)}.nx-download-stats>div+div{border-top:1px solid var(--nx-line);border-left:0}.nx-dashboard-side{grid-template-columns:1fr 1fr;display:grid}.nx-dashboard-side>.nx-modes{grid-column:1/-1}.nx-dashboard-side .nx-mode-options{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;display:grid}.nx-dashboard-side .nx-mode{align-items:flex-start;gap:7px;padding:10px 8px}.nx-dashboard-side .nx-mode>svg{display:none}.nx-dashboard-side .nx-mode-dot{width:12px;height:12px;margin-top:2px}.nx-mode small{font-size:10px}.nx-acceleration-copy p{font-size:11px}.nx-acceleration>.nx-button{padding-inline:12px;font-size:11px}.nx-section-heading{gap:10px}.nx-section-heading p{font-size:11px}.nx-form-grid{grid-template-columns:1fr}.nx-application-actions{grid-template-columns:1fr;gap:22px}.nx-plot{height:160px}.nx-node-list--compact{max-height:190px}}@container nx-shell (width<=520px){.nx-sidebar{flex-basis:59px;width:59px;padding:18px 6px 12px}.nx-brand{padding-bottom:18px}.nx-brand span{display:none}.nx-nav-item{border-radius:9px;gap:4px;min-height:47px}.nx-nav-item span{font-size:10px}.nx-nav-item svg{width:18px;height:18px}.nx-nav-divider{margin-block:11px}.nx-sidebar-foot>span:last-child{display:none}.nx-header{padding:20px 16px 18px}.nx-header h1{font-size:23px}.nx-header p{font-size:11px}.nx-content{padding:0 16px 22px}.nx-notice{margin:0 16px 14px}.nx-header-actions{gap:5px}.nx-live-label{font-size:10px}.nx-live-label>.nx-live-dot{display:none}.nx-acceleration{flex-wrap:wrap;gap:12px;padding:17px}.nx-acceleration-copy{min-width:130px}.nx-acceleration-copy h2{gap:7px}.nx-acceleration>.nx-button{min-height:34px;margin-left:56px}.nx-acceleration-icon{flex-basis:42px;width:42px;height:42px}.nx-panel{padding:16px}.nx-dashboard,.nx-view-stack{gap:16px}.nx-dashboard-side{grid-template-columns:minmax(0,1fr)}.nx-dashboard-side>.nx-modes{grid-column:auto}.nx-dashboard-side .nx-mode-options{display:flex}.nx-dashboard-side .nx-mode>svg{display:block}.nx-dashboard-side .nx-mode{align-items:center}.nx-plot{height:140px}.nx-speed-values{gap:23px}.nx-speed-values strong{font-size:16px}.nx-inline-form{gap:8px}.nx-inline-form>.nx-button{padding-inline:10px;font-size:11px}.nx-inline-form .nx-fit-select{min-width:82px;font-size:11px}.nx-site-shortcuts{gap:1px}.nx-site-shortcuts>span{width:100%;margin-bottom:3px}.nx-download-row{grid-template-columns:28px minmax(0,1fr) auto;gap:10px;padding-block:19px}.nx-file-icon{border-radius:8px;width:28px;height:35px}.nx-file-icon>svg{width:17px}.nx-task-title{flex-direction:column;align-items:flex-start;gap:3px}.nx-task-title>strong{max-width:100%;font-size:12px}.nx-task-title>span{font-size:9px}.nx-task-controls{gap:1px}.nx-task-controls>.nx-icon-button{min-width:27px;padding:4px}.nx-task-meta{gap:4px;font-size:9px}.nx-task-meta>span{width:100%}.nx-task-details{grid-column:1/-1;padding-top:14px}.nx-filter-tabs>button{padding-inline:8px;font-size:11px}.nx-task-list{padding-block:0}.nx-diagnose-start{padding:24px 16px 18px}.nx-diagnose-start>h2{font-size:17px}.nx-diagnose-start>.nx-inline-form{margin-top:18px}.nx-diagnose-options{gap:12px;font-size:10px}.nx-check-row{grid-template-columns:18px minmax(0,1fr) auto 47px;gap:8px}.nx-check-row strong{font-size:11px}.nx-check-row time{font-size:10px}.nx-history-row{gap:9px}.nx-history-row>span:not(.nx-history-result){display:none}.nx-history-row>time{font-size:9px}.nx-section-heading>div{min-width:0}.nx-section-heading h2{font-size:13px}.nx-section-heading>.nx-button{padding-inline:9px;font-size:11px}.nx-schedule-form{flex-wrap:wrap}.nx-schedule-form>.nx-input:first-child{flex-basis:100%}.nx-schedule-row{gap:8px}.nx-schedule-row>.nx-button:not(.nx-icon-button){padding-inline:5px;font-size:10px}.nx-schedule-row strong{font-size:11px}.nx-settings-rows>div{gap:12px}.nx-settings-rows small{font-size:10px}.nx-event{gap:8px;font-size:11px}.nx-event>time{font-size:9px}.nx-rule-row{grid-template-columns:minmax(0,1fr) 96px 24px;gap:5px}.nx-rule-row .nx-input{padding-inline:8px;font-size:11px}.nx-loading-grid{grid-template-columns:1fr}.nx-loading-grid>.nx-skeleton:last-child{display:none}}@media (prefers-reduced-motion:reduce){.nx-app *{scroll-behavior:auto!important;transition:none!important;animation:none!important}}";
//#endregion
//#region ../src/lamtools_core/plugins/bundled/network-exploration/ui/src/page.mjs
function Qf(e, t) {
	if (t.addStyle) return t.addStyle(Zf);
	let n = e.ownerDocument, r = n.createElement("style");
	return r.nonce = n.querySelector("style[nonce]")?.nonce || "", r.dataset.networkPluginStyle = "true", r.textContent = Zf, n.head.append(r), () => r.remove();
}
function $f(e, t) {
	return tp(e, t, Pf);
}
function ep(e, t) {
	return tp(e, t, Xf);
}
function tp(e, t, n) {
	let r = Qf(e, t), i = !1, a = document.createElement("div");
	a.className = n === Xf ? "nx-mount nx-mount--quick" : "nx-mount", e.append(a), np++;
	let o = e.closest(".split-plugin-page");
	o?.classList.add("nx-host");
	let s = e.closest(".workspace-main");
	s?.classList.add("nx-plugin-full");
	let c = is(n, { context: t });
	c.config.idPrefix = `network-${np}`;
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
var np = 0;
//#endregion
export { $f as mount, ep as mountQuick };
