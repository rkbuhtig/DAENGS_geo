package com.daengs.geo.walk.store

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * The app's local database. Schema JSON is exported to `app/schemas` and committed, so a table
 * change shows up in review and a migration can be written against a known previous version.
 */
@Database(
    entities = [WalkSessionRow::class, WalkFixRow::class],
    version = 1,
    exportSchema = true,
)
abstract class DaengsDatabase : RoomDatabase() {
    abstract fun walkDao(): WalkDao

    companion object {
        private const val NAME = "daengs.db"

        fun open(context: Context): DaengsDatabase =
            Room.databaseBuilder(context.applicationContext, DaengsDatabase::class.java, NAME)
                .build()
    }
}
