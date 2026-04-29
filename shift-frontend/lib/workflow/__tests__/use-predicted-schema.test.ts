import { describe, it, expect } from "vitest"
import { isColumnInSchema, staleColumns } from "../use-predicted-schema"
import type { FieldDescriptor } from "@/lib/auth"

const fd = (name: string): FieldDescriptor => ({
  name,
  data_type: "VARCHAR",
  nullable: true,
})

describe("isColumnInSchema", () => {
  it("retorna true quando schema é null (sem dados pra invalidar)", () => {
    expect(isColumnInSchema(null, "qualquer")).toBe(true)
  })

  it("retorna true quando coluna existe no schema", () => {
    expect(isColumnInSchema([fd("id"), fd("nome")], "id")).toBe(true)
  })

  it("retorna false quando coluna não existe no schema", () => {
    expect(isColumnInSchema([fd("id")], "ausente")).toBe(false)
  })
})

describe("staleColumns", () => {
  it("vazia quando schema é null", () => {
    expect(staleColumns(null, ["a", "b"])).toEqual([])
  })

  it("retorna apenas as colunas ausentes do schema", () => {
    const schema = [fd("id"), fd("nome")]
    expect(staleColumns(schema, ["id", "removida", "nome"])).toEqual(["removida"])
  })

  it("deduplica entradas repetidas", () => {
    expect(staleColumns([fd("x")], ["a", "a", "b"])).toEqual(["a", "b"])
  })

  it("ignora strings vazias", () => {
    expect(staleColumns([fd("x")], ["", "y", ""])).toEqual(["y"])
  })
})
