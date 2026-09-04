-- A do-nothing mw.wikibase, so modules that reach for Wikidata degrade to
-- "no data" instead of throwing. Nothing here fetches anything: this mirror
-- has no Wikidata repository and deliberately makes no network calls.
local wikibase = {}

function wikibase.setupInterface()
    mw_interface = nil
    mw.wikibase = wikibase
    package.loaded['mw.wikibase'] = wikibase
end

local function nothing() return nil end
local function emptyTable() return {} end
local function no() return false end

wikibase.getEntity = nothing
wikibase.getEntityObject = nothing
wikibase.getEntityIdForCurrentPage = nothing
wikibase.getEntityIdForTitle = nothing
wikibase.getLabel = nothing
wikibase.getLabelByLang = nothing
wikibase.getLabelWithLang = nothing
wikibase.getDescription = nothing
wikibase.getDescriptionWithLang = nothing
wikibase.getSitelink = nothing
wikibase.getBadges = emptyTable
wikibase.getBestStatements = emptyTable
wikibase.getAllStatements = emptyTable
wikibase.getReferencedEntityId = nothing
wikibase.renderSnak = nothing
wikibase.renderSnaks = nothing
wikibase.formatValue = nothing
wikibase.formatValues = nothing
wikibase.resolvePropertyId = nothing
wikibase.getPropertyOrder = nothing
wikibase.orderProperties = function( properties ) return properties end
wikibase.isValidEntityId = no
wikibase.entityExists = no
wikibase.getGlobalSiteId = function() return 'localwiktionary' end

-- The real client exposes short aliases beside the get* forms.
wikibase.label = nothing
wikibase.sitelink = nothing
wikibase.description = nothing
wikibase.id = nothing
wikibase.getEntityUrl = nothing
wikibase.getEntityIdForCurrentPage = nothing
wikibase.getPropertyOrder = nothing

-- Anything else a module reaches for answers "no data" rather than blowing up:
-- this stub cannot know every entry point the client publishes.
setmetatable( wikibase, { __index = function() return nothing end } )

return wikibase
