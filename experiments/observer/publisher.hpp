#pragma once
#include <algorithm>
#include <vector>

#include "subscriber.hpp"

class publisher {
  public:
    void register_sub(subscriber *sub) {
        if (std::find(subs_.begin(), subs_.end(), sub) == subs_.end()) {
            subs_.push_back(sub);
        }
    }

    void unregister(subscriber *sub) {
        auto it = std::find(subs_.begin(), subs_.end(), sub);
        if (it != subs_.end()) {
            subs_.erase(it);
        }
    }

    void notify(float value) {
        for (auto sub : subs_) {
            sub->update(value);
        }
    }

  private:
    std::vector<subscriber *> subs_;
};
