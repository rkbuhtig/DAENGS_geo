package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import kotlin.math.PI
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/** A deterministic, pure Kotlin grid for the offline map experiment. It is intentionally not H3. */
class LocalHexCellIndexer(
    private val radiusMeters: Double = 28.0,
) : CellIndexer {
    init {
        require(radiusMeters > 0) { "육각 셀 반지름은 0보다 커야 합니다." }
    }

    override fun cellAt(point: GeoPoint): TerritoryCell {
        val projected = point.toMercator()
        val fractionalQ = (sqrt(3.0) / 3.0 * projected.x - projected.y / 3.0) / radiusMeters
        val fractionalR = (2.0 / 3.0 * projected.y) / radiusMeters
        val axial = roundAxial(fractionalQ, fractionalR)
        val center = ProjectedPoint(
            x = radiusMeters * sqrt(3.0) * (axial.q + axial.r / 2.0),
            y = radiusMeters * 1.5 * axial.r,
        )
        val boundary = (0 until 6).map { index ->
            // Clockwise order is required by NAVER PolygonOverlay.
            val angle = Math.toRadians(30.0 - 60.0 * index)
            ProjectedPoint(
                x = center.x + radiusMeters * cos(angle),
                y = center.y + radiusMeters * sin(angle),
            ).toGeoPoint()
        }
        val size = radiusMeters.roundToInt()
        return TerritoryCell(
            id = "local-hex:$size:${axial.q}:${axial.r}",
            center = center.toGeoPoint(),
            boundary = boundary,
        )
    }
}

private data class Axial(val q: Int, val r: Int)
private data class ProjectedPoint(val x: Double, val y: Double)

private fun roundAxial(q: Double, r: Double): Axial {
    val x = q
    val z = r
    val y = -x - z
    var rx = x.roundToInt()
    var ry = y.roundToInt()
    var rz = z.roundToInt()
    val xDiff = kotlin.math.abs(rx - x)
    val yDiff = kotlin.math.abs(ry - y)
    val zDiff = kotlin.math.abs(rz - z)
    when {
        xDiff > yDiff && xDiff > zDiff -> rx = -ry - rz
        yDiff > zDiff -> ry = -rx - rz
        else -> rz = -rx - ry
    }
    return Axial(q = rx, r = rz)
}

private const val EARTH_RADIUS_METERS = 6_378_137.0

private fun GeoPoint.toMercator(): ProjectedPoint {
    val safeLatitude = latitude.coerceIn(-85.0, 85.0)
    return ProjectedPoint(
        x = EARTH_RADIUS_METERS * Math.toRadians(longitude),
        y = EARTH_RADIUS_METERS * ln(tan(PI / 4.0 + Math.toRadians(safeLatitude) / 2.0)),
    )
}

private fun ProjectedPoint.toGeoPoint(): GeoPoint = GeoPoint(
    latitude = Math.toDegrees(2.0 * atan(exp(y / EARTH_RADIUS_METERS)) - PI / 2.0),
    longitude = Math.toDegrees(x / EARTH_RADIUS_METERS),
)
