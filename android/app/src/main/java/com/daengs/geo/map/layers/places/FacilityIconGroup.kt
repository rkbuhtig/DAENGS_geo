package com.daengs.geo.map.layers.places

import androidx.annotation.DrawableRes
import com.daengs.geo.R

/**
 * Marker icon buckets. The server decides which bucket a facility falls into
 * (`icon_group` in the search response) because the source `kind` list grows with
 * every new dataset; the app only maps a known bucket to a drawable.
 *
 * An unknown wire value is [ETC], never a dropped marker — a facility we cannot
 * classify still exists on the map.
 */
enum class FacilityIconGroup(val wire: String, @DrawableRes val marker: Int) {
    MEDICAL("medical", R.drawable.ic_facility_medical),
    SUPPLY("supply", R.drawable.ic_facility_supply),
    FOOD("food", R.drawable.ic_facility_food),
    STAY("stay", R.drawable.ic_facility_stay),
    CULTURE("culture", R.drawable.ic_facility_culture),
    OUTDOOR("outdoor", R.drawable.ic_facility_outdoor),
    CARE("care", R.drawable.ic_facility_care),
    ETC("etc", R.drawable.ic_facility_etc),
    ;

    companion object {
        private val BY_WIRE = entries.associateBy { it.wire }

        fun fromWire(value: String?): FacilityIconGroup = BY_WIRE[value] ?: ETC
    }
}
