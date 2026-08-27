package com.daengs.geo.place

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.FacilityIconGroup
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Canonical kind vocabulary exposed by the server's `PlaceKind` schema. */
enum class PlaceKind(val wire: String) {
    HOSPITAL("hospital"),
    PHARMACY("pharmacy"),
    PET_SHOP("pet_shop"),
    SHOPPING("shopping"),
    GROOMING("grooming"),
    BOARDING("boarding"),
    TRAVEL("travel"),
    LEISURE("leisure"),
    MUSEUM("museum"),
    GALLERY("gallery"),
    ARTS_CENTER("arts_center"),
    CULTURE("culture"),
    CAFE("cafe"),
    RESTAURANT("restaurant"),
    PENSION("pension"),
    HOTEL("hotel"),
    STAY("stay"),
    ETC("etc"),
    ;

    companion object {
        private val byWire = entries.associateBy(PlaceKind::wire)

        fun fromWire(value: String): PlaceKind = requireNotNull(byWire[value]) {
            "Unknown canonical PlaceKind: $value"
        }
    }
}

/**
 * 병원·약국은 계약상 주차 사실을 제공하지 않는다. 선호를 보내도 서버가 쓸 사실이 없으므로
 * 요청과 화면 양쪽에서 같은 판단을 쓴다.
 */
fun PlaceKind.supportsParkingPreference(): Boolean =
    this != PlaceKind.HOSPITAL && this != PlaceKind.PHARMACY

enum class DogSize(val wire: String) {
    SMALL("small"),
    MEDIUM("medium"),
    LARGE("large"),
}

enum class PlaceSortType {
    DISTANCE,
    DISTANCE_PREFERRED,
    ;

    companion object {
        fun fromWire(value: String): PlaceSortType = when (value) {
            "distance" -> DISTANCE
            "distance_preferred" -> DISTANCE_PREFERRED
            else -> throw IllegalArgumentException("Unknown PlaceSortType: $value")
        }
    }
}

enum class DogAccessState {
    COMPATIBLE,
    INCOMPATIBLE,
    UNKNOWN,
    ;

    companion object {
        fun fromWire(value: String): DogAccessState = when (value) {
            "compatible" -> COMPATIBLE
            "incompatible" -> INCOMPATIBLE
            "unknown" -> UNKNOWN
            else -> throw IllegalArgumentException("Unknown DogAccessState: $value")
        }
    }
}

/** Stable source-record identity. This is deliberately not an internal database id. */
data class PlaceKey(
    val source: String,
    val ref: String,
)

data class PlaceClassification(
    val source: PlaceKey,
    val sourceCategory: String,
    val kind: PlaceKind,
    val mappingVersion: String,
    val asOf: String?,
)

data class PlaceMatch(
    val source: PlaceKey,
    val kind: PlaceKind,
)

data class FieldProvenance(
    val source: PlaceKey,
    val asOf: String?,
)

data class PetAccessFacts(
    val raw: JsonObject,
    val allowed: Boolean?,
    val exclusive: Boolean?,
    val dogOk: Boolean?,
    val sizeClass: String?,
    val maxKg: Double?,
)

data class TimeRange(
    val opensAt: String,
    val closesAt: String,
)

data class MedicalFacts(
    val active: Boolean,
    val licenseStatusCode: String?,
    val licenseStatusName: String?,
    val openNow: Boolean?,
    val hoursToday: List<TimeRange>?,
    val areaSquareMeters: Double?,
    val staffCount: Int?,
)

/** Nullable booleans remain three-state facts: unknown is never converted to false. */
data class PlaceFacts(
    val address: String?,
    val phone: String?,
    val homepage: String?,
    val hoursText: String?,
    val closedDays: String?,
    val parking: Boolean?,
    val indoor: Boolean?,
    val outdoor: Boolean?,
    val petAccess: PetAccessFacts?,
    val medical: MedicalFacts?,
)

data class PlaceResult(
    val key: PlaceKey,
    val aliases: List<PlaceKey>,
    val name: String,
    val point: GeoPoint,
    val distanceMeters: Int,
    val match: PlaceMatch,
    val classifications: List<PlaceClassification>,
    val facts: PlaceFacts,
    val fieldSources: Map<String, FieldProvenance>,
    val iconGroup: FacilityIconGroup,
)

data class DogAccessEvaluation(
    val state: DogAccessState,
    /** Kept as a wire string so a newly added server reason is not discarded. */
    val reason: String,
)

data class PlaceEvaluations(
    val dogAccess: DogAccessEvaluation?,
)

data class PlaceSearchHit(
    val place: PlaceResult,
    val evaluations: PlaceEvaluations,
)

data class BooleanFactCoverage(
    val knownTrue: Int,
    val knownFalse: Int,
    val unknown: Int,
)

data class PlaceSort(
    val type: PlaceSortType,
    /** Server-owned ranking vocabulary, kept in order for honest UI explanations. */
    val basis: List<String>,
    val applied: List<String>,
    val bandMeters: Int?,
    val coverage: Map<String, BooleanFactCoverage>,
)

data class PlaceSearchGroup(
    val kind: PlaceKind,
    val sort: PlaceSort,
    val limit: Int,
    val truncated: Boolean,
    val results: List<PlaceSearchHit>,
)

data class AppliedPlaceSearchConditions(
    val dogId: String?,
    val dogSize: String?,
    val dogWeightKg: Double?,
)

data class PlaceSearchResponse(
    val conditions: AppliedPlaceSearchConditions?,
    /** The server preserves requested kind order; the client must preserve group order too. */
    val groups: List<PlaceSearchGroup>,
)

fun JsonObject.toPlaceSearchResponse(): PlaceSearchResponse = PlaceSearchResponse(
    conditions = objectOrNull("conditions")?.toAppliedConditions(),
    groups = getValue("groups").jsonArray.map { it.jsonObject.toPlaceSearchGroup() },
)

private fun JsonObject.toAppliedConditions(): AppliedPlaceSearchConditions =
    AppliedPlaceSearchConditions(
        dogId = stringOrNull("dog_id"),
        dogSize = stringOrNull("dog_size"),
        dogWeightKg = doubleOrNull("dog_weight_kg"),
    )

private fun JsonObject.toPlaceSearchGroup(): PlaceSearchGroup = PlaceSearchGroup(
    kind = PlaceKind.fromWire(requiredString("kind")),
    sort = getValue("sort").jsonObject.toPlaceSort(),
    limit = getValue("limit").jsonPrimitive.int,
    truncated = getValue("truncated").jsonPrimitive.boolean,
    results = getValue("results").jsonArray.map { it.jsonObject.toPlaceSearchHit() },
)

private fun JsonObject.toPlaceSort(): PlaceSort = PlaceSort(
    type = PlaceSortType.fromWire(requiredString("type")),
    basis = arrayOrEmpty("basis").map { it.jsonPrimitive.content },
    applied = arrayOrEmpty("applied").map { it.jsonPrimitive.content },
    bandMeters = intOrNull("band_m"),
    coverage = objectOrNull("coverage")?.mapValues { (_, value) ->
        value.jsonObject.toBooleanFactCoverage()
    }.orEmpty(),
)

private fun JsonObject.toBooleanFactCoverage(): BooleanFactCoverage = BooleanFactCoverage(
    knownTrue = getValue("known_true").jsonPrimitive.int,
    knownFalse = getValue("known_false").jsonPrimitive.int,
    unknown = getValue("unknown").jsonPrimitive.int,
)

private fun JsonObject.toPlaceSearchHit(): PlaceSearchHit = PlaceSearchHit(
    place = getValue("place").jsonObject.toPlaceResult(),
    evaluations = objectOrNull("evaluations")?.toPlaceEvaluations()
        ?: PlaceEvaluations(dogAccess = null),
)

private fun JsonObject.toPlaceEvaluations(): PlaceEvaluations = PlaceEvaluations(
    dogAccess = objectOrNull("dog_access")?.let { value ->
        DogAccessEvaluation(
            state = DogAccessState.fromWire(value.requiredString("state")),
            reason = value.requiredString("reason"),
        )
    },
)

private fun JsonObject.toPlaceResult(): PlaceResult = PlaceResult(
    key = getValue("key").jsonObject.toPlaceKey(),
    aliases = arrayOrEmpty("aliases").map { it.jsonObject.toPlaceKey() },
    name = requiredString("name"),
    point = GeoPoint(
        latitude = getValue("lat").jsonPrimitive.double,
        longitude = getValue("lng").jsonPrimitive.double,
    ),
    distanceMeters = getValue("distance_m").jsonPrimitive.int,
    match = getValue("match").jsonObject.toPlaceMatch(),
    classifications = getValue("classifications").jsonArray.map {
        it.jsonObject.toPlaceClassification()
    },
    facts = getValue("facts").jsonObject.toPlaceFacts(),
    fieldSources = objectOrNull("field_sources")?.mapValues { (_, value) ->
        value.jsonObject.toFieldProvenance()
    }.orEmpty(),
    iconGroup = FacilityIconGroup.fromWire(stringOrNull("icon_group")),
)

private fun JsonObject.toPlaceKey(): PlaceKey = PlaceKey(
    source = requiredString("source"),
    ref = requiredString("ref"),
)

private fun JsonObject.toPlaceMatch(): PlaceMatch = PlaceMatch(
    source = getValue("source").jsonObject.toPlaceKey(),
    kind = PlaceKind.fromWire(requiredString("kind")),
)

private fun JsonObject.toPlaceClassification(): PlaceClassification = PlaceClassification(
    source = getValue("source").jsonObject.toPlaceKey(),
    sourceCategory = requiredString("source_category"),
    kind = PlaceKind.fromWire(requiredString("kind")),
    mappingVersion = requiredString("mapping_version"),
    asOf = stringOrNull("as_of"),
)

private fun JsonObject.toFieldProvenance(): FieldProvenance = FieldProvenance(
    source = getValue("source").jsonObject.toPlaceKey(),
    asOf = stringOrNull("as_of"),
)

private fun JsonObject.toPlaceFacts(): PlaceFacts = PlaceFacts(
    address = stringOrNull("address"),
    phone = stringOrNull("phone"),
    homepage = stringOrNull("homepage"),
    hoursText = stringOrNull("hours_text"),
    closedDays = stringOrNull("closed_days"),
    parking = booleanOrNull("parking"),
    indoor = booleanOrNull("indoor"),
    outdoor = booleanOrNull("outdoor"),
    petAccess = objectOrNull("pet_access")?.toPetAccessFacts(),
    medical = objectOrNull("medical")?.toMedicalFacts(),
)

private fun JsonObject.toPetAccessFacts(): PetAccessFacts = PetAccessFacts(
    raw = objectOrNull("raw") ?: JsonObject(emptyMap()),
    allowed = booleanOrNull("allowed"),
    exclusive = booleanOrNull("exclusive"),
    dogOk = booleanOrNull("dog_ok"),
    sizeClass = stringOrNull("size_class"),
    maxKg = doubleOrNull("max_kg"),
)

private fun JsonObject.toMedicalFacts(): MedicalFacts = MedicalFacts(
    active = getValue("active").jsonPrimitive.boolean,
    licenseStatusCode = stringOrNull("license_status_code"),
    licenseStatusName = stringOrNull("license_status_name"),
    openNow = booleanOrNull("open_now"),
    hoursToday = arrayOrNull("hours_today")?.map { range ->
        val values = range.jsonArray
        require(values.size == 2) { "medical hours_today entries must have two values" }
        TimeRange(
            opensAt = values[0].jsonPrimitive.content,
            closesAt = values[1].jsonPrimitive.content,
        )
    },
    areaSquareMeters = doubleOrNull("area_m2"),
    staffCount = intOrNull("staff_count"),
)

private fun JsonObject.arrayOrNull(name: String): JsonArray? =
    get(name)?.takeUnless { it is JsonNull }?.jsonArray

private fun JsonObject.arrayOrEmpty(name: String): JsonArray =
    arrayOrNull(name) ?: JsonArray(emptyList())

private fun JsonObject.objectOrNull(name: String): JsonObject? =
    get(name)?.takeUnless { it is JsonNull }?.jsonObject

private fun JsonObject.stringOrNull(name: String): String? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.contentOrNull

private fun JsonObject.requiredString(name: String): String = getValue(name).jsonPrimitive.content

private fun JsonObject.booleanOrNull(name: String): Boolean? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.booleanOrNull

private fun JsonObject.doubleOrNull(name: String): Double? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.doubleOrNull

private fun JsonObject.intOrNull(name: String): Int? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.intOrNull
