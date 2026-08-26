package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import java.io.File
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
 * So both read the same file, `docs/contracts/hex-grid-golden.json`.
 *
 * If these values must change, the grid changed — and every stored cell id changes meaning with
 * it (`anchor.cell`, 480k rows). Decide the migration before regenerating the golden file.
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

    private fun goldenFile(): File {
        // Gradle runs unit tests with the module directory as the working directory, but do not
        // rely on how deep that is — walk up until the contract turns up.
        var dir: File? = File(".").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "docs/contracts/hex-grid-golden.json")
            if (candidate.exists()) return candidate
            dir = dir.parentFile
        }
        throw AssertionError("hex-grid-golden.json not found from ${File(".").absolutePath}")
    }

    private fun cases(): List<Case> =
        Json.parseToJsonElement(goldenFile().readText())
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
