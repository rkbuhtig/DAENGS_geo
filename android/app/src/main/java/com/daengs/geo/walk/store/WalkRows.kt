package com.daengs.geo.walk.store

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.PrimaryKey

@Entity(tableName = "walk_session")
data class WalkSessionRow(
    @PrimaryKey val id: String,
    val dogId: String?,
    val startedAtMillis: Long,
    /** Null means the walk was never closed — process death, force stop, or still running. */
    val endedAtMillis: Long?,
)

/**
 * `clientSeq` is part of the key, not an autoincrement id: it is the client's own ordering, so a
 * fix written twice collapses into one row instead of duplicating the walk.
 */
@Entity(
    tableName = "walk_fix",
    primaryKeys = ["sessionId", "clientSeq"],
    foreignKeys = [
        ForeignKey(
            entity = WalkSessionRow::class,
            parentColumns = ["id"],
            childColumns = ["sessionId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
)
data class WalkFixRow(
    val sessionId: String,
    val clientSeq: Int,
    val chainIndex: Int,
    val atMillis: Long,
    val lat: Double,
    val lng: Double,
    val accuracyM: Float?,
    val isMock: Boolean,
)
