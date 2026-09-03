package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Hex grid golden vector — Kotlin side.
 *
 * `app/geo/cells.py` claims Python, Android and the ingest share one cell id space. A test that
 * only runs in one language cannot keep that claim: both sides can pass while disagreeing.
 * So both check the same vector: this module bundles a copy as a test resource, and
 * `tests/geo/test_cells_golden.py` reads `docs/contracts/hex-grid-golden.json` and fails if the
 * two stop matching.
 *
 * If these values must change, the grid changed — and every stored cell id changes meaning with
 * it (`territory_site.site_id`). Decide the migration before regenerating the golden file.
 *
 * Parsed with `parseToJsonElement` rather than `@Serializable` data classes: the golden file is
 * read in exactly one place, and this keeps the test independent of the serialization plugin.
 */
class HexGridGoldenTest {

    private data class Case(
        val lat: Double,
        val lng: Double,
        val radiusU: Double,
        val q: Int,
        val r: Int,
        val note: String,
    )

    /**
     * The bundled copy of `docs/contracts/hex-grid-golden.json`, not the file itself.
     *
     * The module must build wherever it lives, so it cannot reach out to a sibling directory in
     * this repository. A drifting copy would defeat the point, so `tests/geo/test_cells_golden.py`
     * fails if the two files stop being byte-identical — and drift is bounded anyway: `hex-v1` is
     * frozen by definition, and changing the grid means a new version, not an edited file.
     */
    private fun goldenText(): String =
        javaClass.getResource("/hex-grid-golden.json")!!.readText()

    private fun cases(): List<Case> =
        Json.parseToJsonElement(goldenText())
            .jsonObject["cases"]!!
            .jsonArray
            .map { element ->
                val row = element.jsonObject
                Case(
                    lat = row["lat"]!!.jsonPrimitive.double,
                    lng = row["lng"]!!.jsonPrimitive.double,
                    radiusU = row["radius_u"]!!.jsonPrimitive.double,
                    q = row["q"]!!.jsonPrimitive.int,
                    r = row["r"]!!.jsonPrimitive.int,
                    note = row["note"]?.jsonPrimitive?.content ?: "",
                )
            }

    @Test
    fun `golden cases match the shared grid`() {
        val cases = cases()
        assertTrue("golden is empty", cases.isNotEmpty())
        for (case in cases) {
            val cell = LocalHexCellIndexer(radiusMeters = case.radiusU)
                .cellAt(GeoPoint(case.lat, case.lng))
            // id is "local-hex:<size>:<q>:<r>" — only the axial pair is the shared contract.
            val parts = cell.id.split(":")
            val q = parts[parts.size - 2].toInt()
            val r = parts[parts.size - 1].toInt()
            assertEquals("q for ${case.note} @ radius=${case.radiusU}", case.q, q)
            assertEquals("r for ${case.note} @ radius=${case.radiusU}", case.r, r)
        }
    }

    @Test
    fun `golden spans latitudes and radii`() {
        val cases = cases()
        val lats = cases.map { it.lat }
        assertTrue("latitude span too narrow", lats.max() - lats.min() > 30)
        assertTrue(
            "one radius cannot catch a division error",
            cases.map { it.radiusU }.toSet().size >= 3,
        )
    }
}
