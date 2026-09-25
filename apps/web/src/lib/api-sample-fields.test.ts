import { describe, expect, it } from 'vitest'

import { parseSampleJson, sampleFieldOptions, toFieldExpr } from './api-sample-fields'

describe('parseSampleJson', () => {
  it('parses valid JSON and rejects broken text', () => {
    expect(parseSampleJson('{"a":1}')).toEqual({ a: 1 })
    expect(parseSampleJson('[1,2]')).toEqual([1, 2])
    expect(parseSampleJson('{broken')).toBeNull()
  })
})

describe('sampleFieldOptions', () => {
  it('root array: items=[*], field keys from first elements', () => {
    const options = sampleFieldOptions([
      { id: 7, name: 'v1', html_url: 'https://x/7' },
      { id: 6, name: 'v0', extra: true },
    ])
    expect(options.itemsExprs).toEqual(['[*]'])
    expect(options.fieldKeys).toEqual(['id', 'name', 'html_url', 'extra'])
  })

  it('object root with array value: items candidate = key, element keys merged', () => {
    const options = sampleFieldOptions({
      meta: { next: 'cursor-2' },
      items: [{ id: 1, title: 't', published_at: '2026-09-01' }],
    })
    expect(options.itemsExprs).toEqual(['items'])
    expect(options.fieldKeys).toContain('meta')
    expect(options.fieldKeys).toContain('items')
    expect(options.fieldKeys).toContain('id')
    expect(options.fieldKeys).toContain('published_at')
  })

  it('object root scalars: field keys are top-level keys, no items candidates', () => {
    const options = sampleFieldOptions({ id: 1, name: '单条' })
    expect(options.itemsExprs).toEqual([])
    expect(options.fieldKeys).toEqual(['id', 'name'])
  })

  it('non-object samples yield empty options', () => {
    expect(sampleFieldOptions('text').fieldKeys).toEqual([])
    expect(sampleFieldOptions(null).itemsExprs).toEqual([])
  })
})

describe('toFieldExpr', () => {
  it('bare identifiers stay bare; special keys get quoted', () => {
    expect(toFieldExpr('published_at')).toBe('published_at')
    expect(toFieldExpr('html-url')).toBe('"html-url"')
    expect(toFieldExpr('weird key.name')).toBe('"weird key.name"')
    expect(toFieldExpr('标题')).toBe('"标题"')
  })
})
