import { describe, it, expect } from "vitest"
import {
  createFixed,
  createDynamic,
  isParameterValue,
  parameterValueToJson,
  parameterValueFromJson,
  mappingToParameterValue,
  parameterValueToMapping,
  migrateLegacySqlParameter,
  type ParameterValue,
  type TransformEntry,
  type MapperMapping,
} from "../parameter-value"

describe("createFixed", () => {
  it("creates a fixed value object", () => {
    expect(createFixed("hello")).toEqual({ mode: "fixed", value: "hello" })
  })

  it("creates a fixed value with empty string", () => {
    expect(createFixed("")).toEqual({ mode: "fixed", value: "" })
  })
})

describe("createDynamic", () => {
  it("creates a dynamic value without transforms", () => {
    const v = createDynamic("Hello {{name}}")
    expect(v).toEqual({ mode: "dynamic", template: "Hello {{name}}" })
    expect((v as { transforms?: unknown }).transforms).toBeUndefined()
  })

  it("creates a dynamic value with transforms", () => {
    const transforms: TransformEntry[] = [{ kind: "upper" }, { kind: "trim" }]
    expect(createDynamic("{{name}}", transforms)).toEqual({
      mode: "dynamic",
      template: "{{name}}",
      transforms,
    })
  })
})

describe("isParameterValue", () => {
  it("accepts a valid fixed value", () => {
    expect(isParameterValue({ mode: "fixed", value: "x" })).toBe(true)
  })

  it("accepts a valid dynamic value", () => {
    expect(isParameterValue({ mode: "dynamic", template: "{{t}}" })).toBe(true)
  })

  it("accepts a dynamic value with transforms", () => {
    expect(
      isParameterValue({
        mode: "dynamic",
        template: "{{t}}",
        transforms: [{ kind: "upper" }],
      })
    ).toBe(true)
  })

  it("rejects null", () => {
    expect(isParameterValue(null)).toBe(false)
  })

  it("rejects a number", () => {
    expect(isParameterValue(42)).toBe(false)
  })

  it("rejects an unknown mode", () => {
    expect(isParameterValue({ mode: "unknown" })).toBe(false)
  })

  it("rejects fixed without value field", () => {
    expect(isParameterValue({ mode: "fixed" })).toBe(false)
  })

  it("rejects dynamic without template field", () => {
    expect(isParameterValue({ mode: "dynamic" })).toBe(false)
  })

  it("rejects fixed with non-string value", () => {
    expect(isParameterValue({ mode: "fixed", value: 123 })).toBe(false)
  })
})

describe("round-trip serialization", () => {
  it("round-trips a fixed value", () => {
    const v = createFixed("test-value")
    expect(parameterValueFromJson(parameterValueToJson(v))).toEqual(v)
  })

  it("round-trips a dynamic value without transforms", () => {
    const v = createDynamic("Rua {{ENDERECO}} nº {{NUMERO}}")
    expect(parameterValueFromJson(parameterValueToJson(v))).toEqual(v)
  })

  it("round-trips a dynamic value with transforms", () => {
    const v = createDynamic("{{name}}", [
      { kind: "upper" },
      { kind: "replace", args: { old: " ", new: "_" } },
      { kind: "truncate", args: { length: 20 } },
    ])
    expect(parameterValueFromJson(parameterValueToJson(v))).toEqual(v)
  })

  it("parameterValueToJson returns a plain object (not the same reference)", () => {
    const v = createFixed("x")
    const json = parameterValueToJson(v)
    expect(json).toEqual(v)
    expect(json).not.toBe(v)
  })

  it("parameterValueFromJson throws for an invalid payload", () => {
    expect(() => parameterValueFromJson({ mode: "bad" })).toThrow()
    expect(() => parameterValueFromJson(null)).toThrow()
    expect(() => parameterValueFromJson(42)).toThrow()
    expect(() => parameterValueFromJson({ mode: "fixed" })).toThrow()
  })

  it("parameterValueFromJson accepts a raw fixed object", () => {
    const raw = { mode: "fixed", value: "hello" }
    const v = parameterValueFromJson(raw)
    expect(v).toEqual(raw)
  })
})

// ─── Mapper adapter round-trips ───────────────────────────────────────────────

const baseMapping: MapperMapping = {
  target: "output_field",
  type: "string",
  valueType: "static",
}

describe("mappingToParameterValue", () => {
  it("static → fixed", () => {
    const m: MapperMapping = { ...baseMapping, valueType: "static", value: "hello" }
    expect(mappingToParameterValue(m)).toEqual(createFixed("hello"))
  })

  it("static with missing value → fixed empty string", () => {
    const m: MapperMapping = { ...baseMapping, valueType: "static" }
    expect(mappingToParameterValue(m)).toEqual(createFixed(""))
  })

  it("field → dynamic single-chip template", () => {
    const m: MapperMapping = { ...baseMapping, valueType: "field", source: "NOME" }
    const pv = mappingToParameterValue(m)
    expect(pv).toEqual({ mode: "dynamic", template: "{{NOME}}", transforms: [] })
  })

  it("field with simple transforms → dynamic with PV transforms", () => {
    const m: MapperMapping = {
      ...baseMapping,
      valueType: "field",
      source: "NOME",
      transforms: ["upper", "trim"],
    }
    const pv = mappingToParameterValue(m)
    expect(pv.mode).toBe("dynamic")
    if (pv.mode === "dynamic") {
      expect(pv.transforms).toEqual([{ kind: "upper" }, { kind: "trim" }])
    }
  })

  it("field with replace transform → dynamic with replace entry", () => {
    const m: MapperMapping = {
      ...baseMapping,
      valueType: "field",
      source: "ID",
      transforms: [{ id: "replace", params: { from: "-", to: "" } }],
    }
    const pv = mappingToParameterValue(m)
    expect(pv.mode).toBe("dynamic")
    if (pv.mode === "dynamic") {
      expect(pv.transforms).toEqual([{ kind: "replace", args: { old: "-", new: "" } }])
    }
  })

  it("expression → dynamic with exprTemplate", () => {
    const m: MapperMapping = {
      ...baseMapping,
      valueType: "expression",
      exprTemplate: "{{A}} {{B}}",
    }
    const pv = mappingToParameterValue(m)
    expect(pv).toEqual({ mode: "dynamic", template: "{{A}} {{B}}", transforms: [] })
  })
})

describe("parameterValueToMapping", () => {
  it("fixed → static mapping", () => {
    const pv = createFixed("world")
    const result = parameterValueToMapping(pv, baseMapping)
    expect(result.valueType).toBe("static")
    expect(result.value).toBe("world")
    expect(result.source).toBe("")
    expect(result.transforms).toEqual([])
  })

  it("dynamic single-chip → field mapping", () => {
    const pv = createDynamic("{{CAMPO}}")
    const result = parameterValueToMapping(pv, baseMapping)
    expect(result.valueType).toBe("field")
    expect(result.source).toBe("CAMPO")
    expect(result.exprTemplate).toBe("")
  })

  it("dynamic single-chip with transforms → field mapping with transforms", () => {
    const pv = createDynamic("{{NOME}}", [{ kind: "upper" }, { kind: "trim" }])
    const result = parameterValueToMapping(pv, baseMapping)
    expect(result.valueType).toBe("field")
    expect(result.source).toBe("NOME")
    expect(result.transforms).toEqual(["upper", "trim"])
  })

  it("dynamic multi-token → expression mapping", () => {
    const pv = createDynamic("{{A}} e {{B}}")
    const result = parameterValueToMapping(pv, baseMapping)
    expect(result.valueType).toBe("expression")
    expect(result.exprTemplate).toBe("{{A}} e {{B}}")
    expect(result.source).toBe("")
  })

  it("preserves non-value fields from existing mapping", () => {
    const existing: MapperMapping = { ...baseMapping, target: "my_field", type: "integer" }
    const result = parameterValueToMapping(createFixed("42"), existing)
    expect(result.target).toBe("my_field")
    expect(result.type).toBe("integer")
  })
})

describe("adapter round-trips", () => {
  it("static round-trips through PV and back", () => {
    const original: MapperMapping = { ...baseMapping, valueType: "static", value: "abc" }
    const pv = mappingToParameterValue(original)
    const back = parameterValueToMapping(pv, original)
    expect(back.valueType).toBe("static")
    expect(back.value).toBe("abc")
  })

  it("field round-trips through PV and back", () => {
    const original: MapperMapping = {
      ...baseMapping,
      valueType: "field",
      source: "NOME",
      transforms: ["upper"],
    }
    const pv = mappingToParameterValue(original)
    const back = parameterValueToMapping(pv, original)
    expect(back.valueType).toBe("field")
    expect(back.source).toBe("NOME")
    expect(back.transforms).toEqual(["upper"])
  })

  it("expression round-trips through PV and back", () => {
    const original: MapperMapping = {
      ...baseMapping,
      valueType: "expression",
      exprTemplate: "{{A}}-{{B}}",
    }
    const pv = mappingToParameterValue(original)
    const back = parameterValueToMapping(pv, original)
    expect(back.valueType).toBe("expression")
    expect(back.exprTemplate).toBe("{{A}}-{{B}}")
  })
})

// ─── remove_chars round-trip ─────────────────────────────────────────────────

describe("remove_chars adapter round-trip", () => {
  const base: MapperMapping = { target: "out", type: "string", valueType: "field" }

  it("Mapping(remove_chars) → ParameterValue preserves chars arg", () => {
    const m: MapperMapping = {
      ...base,
      source: "FONE",
      transforms: [{ id: "remove_chars", params: { chars: "()-." } }],
    }
    const pv = mappingToParameterValue(m)
    expect(pv.mode).toBe("dynamic")
    if (pv.mode === "dynamic") {
      expect(pv.transforms).toEqual([{ kind: "remove_chars", args: { chars: "()-." } }])
    }
  })

  it("ParameterValue(remove_chars) → Mapping preserves chars arg", () => {
    const pv = createDynamic("{{FONE}}", [{ kind: "remove_chars", args: { chars: "()-." } }])
    const result = parameterValueToMapping(pv, base)
    expect(result.valueType).toBe("field")
    expect(result.source).toBe("FONE")
    expect(result.transforms).toEqual([{ id: "remove_chars", params: { chars: "()-." } }])
  })

  it("full round-trip Mapping → PV → Mapping is lossless", () => {
    const original: MapperMapping = {
      ...base,
      source: "CPF",
      transforms: [{ id: "remove_chars", params: { chars: ".-/" } }],
    }
    const pv = mappingToParameterValue(original)
    const back = parameterValueToMapping(pv, original)
    expect(back.valueType).toBe("field")
    expect(back.source).toBe("CPF")
    expect(back.transforms).toEqual([{ id: "remove_chars", params: { chars: ".-/" } }])
  })

  it("remove_chars with empty chars arg round-trips without error", () => {
    const m: MapperMapping = {
      ...base,
      source: "NOME",
      transforms: [{ id: "remove_chars", params: { chars: "" } }],
    }
    const pv = mappingToParameterValue(m)
    const back = parameterValueToMapping(pv, m)
    expect(back.transforms).toEqual([{ id: "remove_chars", params: { chars: "" } }])
  })
})

// ─── migrateLegacySqlParameter ───────────────────────────────────────────────

describe("migrateLegacySqlParameter", () => {
  it("upstream_results. prefix → dynamic with node_X.CAMPO token", () => {
    const pv = migrateLegacySqlParameter("upstream_results.node_X.data.CAMPO")
    expect(pv).toEqual(createDynamic("{{node_X.data.CAMPO}}", []))
  })

  it("upstream. alias → dynamic with node_X.CAMPO token", () => {
    const pv = migrateLegacySqlParameter("upstream.node_X.CAMPO")
    expect(pv).toEqual(createDynamic("{{node_X.CAMPO}}", []))
  })

  it("plain literal string → fixed", () => {
    const pv = migrateLegacySqlParameter("valor_literal")
    expect(pv).toEqual(createFixed("valor_literal"))
  })

  it("empty string → fixed empty", () => {
    const pv = migrateLegacySqlParameter("")
    expect(pv).toEqual(createFixed(""))
  })

  it("already-valid fixed ParameterValue → returned as-is", () => {
    const input = createFixed("hello")
    expect(migrateLegacySqlParameter(input)).toEqual(input)
  })

  it("already-valid dynamic ParameterValue → returned as-is", () => {
    const input = createDynamic("{{X}}")
    expect(migrateLegacySqlParameter(input)).toEqual(input)
  })

  it("number → fixed string", () => {
    const pv = migrateLegacySqlParameter(42)
    expect(pv).toEqual(createFixed("42"))
  })

  it("null → fixed empty string", () => {
    const pv = migrateLegacySqlParameter(null)
    expect(pv).toEqual(createFixed(""))
  })
})
