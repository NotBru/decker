-- mw.title.newBatch, for a MediaWiki whose Scribunto predates it.
--
-- Wiktionary's Module:zh-glyph calls
--     mw.title.newBatch( titles ):lookupExistence():getTitles()
-- to ask whether a page's glyph-origin images exist. The API arrived in
-- Scribunto after the 1.43 LTS the mirror runs, so every Chinese entry with a
-- glyph box renders `Lua error in Module:zh-glyph at line 63: attempt to call
-- field 'newBatch' (a nil value)` into the page. The definitions are fine --
-- the error sits in a box decker never reads -- but it is an error in the
-- page, and `definition-fetching.md` explains what it used to cost.
--
-- Upstream's batching needs a PHP side (LinkBatchFactory). This is upstream's
-- *other* path, the one it takes when existence was not asked for: one
-- mw.title.new per title, each lazily expensive. Wiktionary asks for a few
-- dozen per page and $wgExpensiveParserFunctionLimit is already 2000.
--
-- Append the function below to, inside the `if` that defines title.new:
--     extensions/Scribunto/includes/Engines/LuaCommon/lualib/mw.title.lua
-- immediately before `function title.new(`. Reapply after a Scribunto update,
-- or drop it once Scribunto ships the real one.

function title.newBatch( list, defaultNamespace )
	local batchObj = {}
	function batchObj:lookupExistence()
		return batchObj
	end
	function batchObj:getTitles()
		local result = {}
		for i, v in pairs( list ) do
			result[i] = title.new( v, defaultNamespace )
		end
		return result
	end
	return batchObj
end
