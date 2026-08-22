package com.daengs.geo.location

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

internal fun GeoPoint.distanceToMeters(other: GeoPoint): Double {
    val earthRadiusMeters = 6_371_000.0
    val lat1 = Math.toRadians(latitude)
    val lat2 = Math.toRadians(other.latitude)
    val latDelta = lat2 - lat1
    val lngDelta = Math.toRadians(other.longitude - longitude)
    val a = sin(latDelta / 2) * sin(latDelta / 2) +
        cos(lat1) * cos(lat2) * sin(lngDelta / 2) * sin(lngDelta / 2)
    return 2 * earthRadiusMeters * atan2(sqrt(a), sqrt(1 - a))
}
